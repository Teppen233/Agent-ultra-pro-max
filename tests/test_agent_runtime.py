"""Agent 运行时与 Team Lead 的结构化输出测试。"""

from datetime import UTC, datetime

import pytest
from pydantic_ai.models.test import TestModel

from reviewcrew.agents.base import AgentRuntime, Budget, ReviewAgentProtocol, VerifierProtocol
from reviewcrew.agents.team_lead import TeamLeadAgent
from reviewcrew.schemas import Budget as SchemaBudget
from reviewcrew.schemas import CodeEvidence, ContextPack, Finding, PRData, ReviewPlan, Verdict


def make_context() -> ContextPack:
    """构造最小上下文。"""

    return ContextPack(
        id="ctx-auth",
        repository="acme/demo",
        base_sha="base",
        head_sha="head",
        pr_title="修复鉴权",
        files=["src/auth.py"],
        diff_hunks=[],
    )


def make_finding() -> Finding:
    """构造有效候选问题。"""

    return Finding(
        id="finding-auth",
        producer="defect",
        category="security",
        severity="high",
        confidence=0.9,
        file="src/auth.py",
        line_start=10,
        line_end=10,
        title="缺少权限校验",
        description="请求可读取不属于当前用户的资源。",
        trigger_condition="攻击者提供其他用户的资源标识。",
        impact="可能泄露数据。",
        reasoning_summary="变更删除了归属校验。",
        evidence=[
            CodeEvidence(
                source="diff",
                file="src/auth.py",
                start_line=10,
                end_line=10,
                description="变更行直接读取资源。",
                content="return repository.get(resource_id)",
            )
        ],
        created_at=datetime.now(UTC),
    )


class Expert(ReviewAgentProtocol):
    """返回有效 Finding 的测试专家。"""

    async def run(self, context: ContextPack) -> list[Finding]:
        return [make_finding()]


class InvalidExpert(ReviewAgentProtocol):
    """返回非法结果的测试专家。"""

    async def run(self, context: ContextPack) -> list[Finding]:
        return [object()]  # type: ignore[list-item]


class CoordinatedExpert(ReviewAgentProtocol):
    """接受团队协作对象的测试专家。"""

    def __init__(self) -> None:
        self.mailbox: object | None = None
        self.blackboard: object | None = None

    async def run(
        self,
        context: ContextPack,
        *,
        mailbox: object | None = None,
        blackboard: object | None = None,
    ) -> list[Finding]:
        self.mailbox = mailbox
        self.blackboard = blackboard
        return [make_finding()]


class Verifier(VerifierProtocol):
    """返回有效 Verdict 的测试校验器。"""

    async def run(self, findings: list[Finding], context: list[ContextPack]) -> list[Verdict]:
        return [
            Verdict(
                finding_id=findings[0].id,
                accepted=True,
                verdict="confirmed",
                confidence=0.9,
                severity="high",
                reason="证据充分。",
            )
        ]


@pytest.mark.asyncio
async def test_runtime_returns_valid_structured_expert_and_verifier_outputs() -> None:
    """运行时接受合法结构化结果并交给校验器。"""

    runtime = AgentRuntime()
    context = make_context()

    findings = await runtime.run_expert(Expert(), context)
    verdicts = await runtime.run_verifier(Verifier(), findings, [context])

    assert findings[0].id == "finding-auth"
    assert verdicts[0].accepted is True


@pytest.mark.asyncio
async def test_runtime_rejects_invalid_structured_output() -> None:
    """运行时拒绝不符合 Finding Schema 的专家输出。"""

    with pytest.raises(ValueError, match="Finding"):
        await AgentRuntime().run_expert(InvalidExpert(), make_context())


@pytest.mark.asyncio
async def test_runtime_adapts_mailbox_and_blackboard_for_future_agents() -> None:
    """运行时向支持协作参数的 Agent 传递 Mailbox 与 Blackboard。"""

    expert = CoordinatedExpert()
    mailbox = object()
    blackboard = object()

    await AgentRuntime().run_expert(expert, make_context(), mailbox=mailbox, blackboard=blackboard)

    assert expert.mailbox is mailbox
    assert expert.blackboard is blackboard


@pytest.mark.asyncio
async def test_runtime_records_tool_event_without_tool_arguments() -> None:
    """工具事件只保留角色和工具名，不保留可能敏感的调用参数。"""

    events: list[tuple[str, dict[str, object]]] = []

    async def capture(name: str, data: dict[str, object]) -> None:
        events.append((name, data))

    runtime = AgentRuntime(event_sink=capture)
    await runtime.record_tool_call("defect", "read_file")

    assert events == [("agent.tool", {"role": "defect", "tool_name": "read_file"})]


@pytest.mark.asyncio
async def test_runtime_enforces_request_limit() -> None:
    """请求数达到预算上限后，运行时拒绝新的模型调用。"""

    runtime = AgentRuntime(budget=Budget(seconds=60, max_requests=1))
    await runtime.run_expert(Expert(), make_context())

    with pytest.raises(RuntimeError, match="请求数"):
        await runtime.run_expert(Expert(), make_context())


def test_budget_is_a_shared_schema_contract() -> None:
    """预算模型位于公共 Schema，供后续编排阶段复用。"""

    budget = SchemaBudget(seconds=60)

    assert budget.remaining_requests == 8


@pytest.mark.asyncio
async def test_team_lead_routes_security_context_to_both_experts_without_findings() -> None:
    """安全风险同时路由给 Defect 和 Intent，Team Lead 只产出计划。"""

    plan = await TeamLeadAgent().plan(
        PRData(
            provider="local",
            repository="acme/demo",
            title="修复鉴权",
            base_sha="base",
            head_sha="head",
            files=[],
            raw_diff="+ token = request.token",
        ),
        [make_context()],
        Budget(seconds=60),
    )

    assert isinstance(plan, ReviewPlan)
    assert set(plan.required_agents) == {"defect", "intent"}
    assert not hasattr(plan, "findings")


@pytest.mark.asyncio
async def test_team_lead_accepts_pydantic_ai_test_model_structured_plan() -> None:
    """Team Lead 可消费 Pydantic AI TestModel 的结构化 ReviewPlan。"""

    model = TestModel(
        custom_output_args={
            "summary": "测试计划",
            "risk_tags": [],
            "required_agents": ["defect"],
            "context_ids": [],
            "shards": {},
            "budget_seconds": 1,
        }
    )
    plan = await TeamLeadAgent(model=model).plan(
        PRData(
            provider="local",
            repository="acme/demo",
            title="普通变更",
            base_sha="base",
            head_sha="head",
            files=[],
            raw_diff="+ value = 1",
        ),
        [make_context()],
        Budget(seconds=60),
    )

    assert plan.summary == "测试计划"
    assert plan.context_ids == ["ctx-auth"]
