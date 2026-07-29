"""Agent 运行时与 Team Lead 的结构化输出测试。"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai.output import PromptedOutput

from reviewcrew.agents.base import AgentRuntime, Budget, PromptSource, ReviewAgentProtocol, VerifierProtocol
from reviewcrew.config import Config
from reviewcrew.hooks import HookContext, HookManager
from reviewcrew.agents.team_lead import TeamLeadAgent
from reviewcrew.schemas import Budget as SchemaBudget
from reviewcrew.schemas import AgentSnapshot, CodeEvidence, ContextPack, Finding, PRData, ReviewPlan, Verdict
from reviewcrew.skills.registry import SkillRegistry


def test_resolve_role_model_builds_configured_model_with_role_override(monkeypatch) -> None:
    """生产构造器应在有密钥时自动按角色模型创建兼容模型。"""

    from reviewcrew.agents import base

    captured: list[Config] = []
    sentinel = object()
    monkeypatch.setattr(base, "build_glm_model", lambda config: captured.append(config) or sentinel)

    resolved = base.resolve_role_model(
        None,
        Config(llm_api_key="secret", llm_model="global", defect_model="defect-model"),
        "defect",
    )

    assert resolved is sentinel
    assert captured[0].llm_model == "defect-model"
    assert "secret" not in repr(captured[0])


def test_resolve_role_model_keeps_fake_mode_without_key() -> None:
    """未配置密钥时保持离线 fallback，不隐式访问网络。"""

    from reviewcrew.agents.base import resolve_role_model

    assert resolve_role_model(None, Config(), "intent") is None


def test_runtime_uses_prompted_output_when_configured() -> None:
    """兼容端点应能切换到提示式 JSON 输出而不改业务代码。"""

    runtime = AgentRuntime(config=Config(llm_output_mode="prompted"))

    assert isinstance(runtime.output_type_for(ReviewPlan), PromptedOutput)


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

    async def run(self, context: ContextPack) -> AgentSnapshot:
        return AgentSnapshot(agent_id="expert", findings=[make_finding()])


class InvalidExpert(ReviewAgentProtocol):
    """返回非法结果的测试专家。"""

    async def run(self, context: ContextPack) -> AgentSnapshot:
        return object()  # type: ignore[return-value]


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
    ) -> AgentSnapshot:
        self.mailbox = mailbox
        self.blackboard = blackboard
        return AgentSnapshot(agent_id="coordinated", findings=[make_finding()])


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


class SensitiveToolTestModel(TestModel):
    """为真实工具生命周期生成包含敏感字段的调用参数。"""

    def gen_tool_args(self, tool_def):  # type: ignore[no-untyped-def]
        if tool_def.name == "read_file":
            return {"path": "/private/secret.py", "access_token": "sensitive-test-token"}
        return super().gen_tool_args(tool_def)


class RecoveringStructuredOutputModel(TestModel):
    """第一次返回非法结构，收到重试后返回合法结构。"""

    def __init__(self) -> None:
        super().__init__(custom_output_args={"summary": "已恢复", "budget_seconds": 1})
        self.request_calls = 0

    async def request(self, messages, model_settings, model_request_parameters):  # type: ignore[no-untyped-def]
        self.request_calls += 1
        self.custom_output_args = (
            {"summary": "非法计划", "budget_seconds": 0}
            if self.request_calls == 1
            else {"summary": "已恢复", "budget_seconds": 1}
        )
        return await super().request(messages, model_settings, model_request_parameters)


class ReservationBarrierModel(TestModel):
    """占住一次真实模型调用，供并发预算测试建立屏障。"""

    def __init__(self) -> None:
        super().__init__(custom_output_args={"summary": "屏障完成", "budget_seconds": 1})
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.request_calls = 0

    async def request(self, messages, model_settings, model_request_parameters):  # type: ignore[no-untyped-def]
        self.request_calls += 1
        self.started.set()
        await self.release.wait()
        return await super().request(messages, model_settings, model_request_parameters)


@pytest.mark.asyncio
async def test_runtime_returns_valid_structured_expert_and_verifier_outputs() -> None:
    """运行时接受合法结构化结果并交给校验器。"""

    runtime = AgentRuntime()
    context = make_context()

    snapshot = await runtime.run_expert(Expert(), context)
    findings = snapshot.findings
    verdicts = await runtime.run_verifier(Verifier(), findings, [context])

    assert findings[0].id == "finding-auth"
    assert verdicts[0].accepted is True


@pytest.mark.asyncio
async def test_runtime_rejects_invalid_structured_output() -> None:
    """运行时拒绝不符合 Finding Schema 的专家输出。"""

    with pytest.raises(ValueError, match="AgentSnapshot"):
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
async def test_runtime_emits_redacted_event_from_real_pydantic_ai_tool_lifecycle(tmp_path) -> None:
    """真实函数工具调用只向运行时事件暴露角色和工具名。"""

    shared = tmp_path / "shared.md"
    role_prompt = tmp_path / "role.md"
    shared.write_text("共享规则", encoding="utf-8")
    role_prompt.write_text("角色提示", encoding="utf-8")
    events: list[tuple[str, dict[str, object]]] = []
    tool_arguments: list[tuple[str, str]] = []

    async def capture(name: str, data: dict[str, object]) -> None:
        events.append((name, data))

    async def read_file(path: str, access_token: str) -> str:
        tool_arguments.append((path, access_token))
        return "文件内容"

    runtime = AgentRuntime(event_sink=capture)
    output = await runtime.run_structured(
        SensitiveToolTestModel(
            call_tools=["read_file"],
            custom_output_args={"summary": "工具调用完成", "budget_seconds": 1},
        ),
        role="defect",
        sources=[PromptSource("shared", shared), PromptSource("role", role_prompt)],
        skills=[],
        dynamic_context="上下文",
        budget=Budget(seconds=60),
        output_type=ReviewPlan,
        tools=[read_file],
    )

    assert output.summary == "工具调用完成"
    assert tool_arguments == [("/private/secret.py", "sensitive-test-token")]
    assert events == [("agent.tool", {"role": "defect", "tool_name": "read_file"})]
    assert "/private/secret.py" not in repr(events)
    assert "sensitive-test-token" not in repr(events)


@pytest.mark.asyncio
async def test_runtime_recovers_after_one_invalid_structured_output_and_counts_both_requests(tmp_path) -> None:
    """结构化输出首次非法时重试一次，并精确记录两次模型请求。"""

    shared = tmp_path / "shared.md"
    role_prompt = tmp_path / "role.md"
    shared.write_text("共享规则", encoding="utf-8")
    role_prompt.write_text("角色提示", encoding="utf-8")
    budget = Budget(seconds=60, max_requests=2)
    model = RecoveringStructuredOutputModel()
    runtime = AgentRuntime(config=Config(llm_max_retries=1))

    output = await runtime.run_structured(
        model,
        role="team_lead",
        sources=[PromptSource("shared", shared), PromptSource("role", role_prompt)],
        skills=[],
        dynamic_context="上下文",
        budget=budget,
        output_type=ReviewPlan,
    )

    assert output.summary == "已恢复"
    assert model.request_calls == 2
    assert runtime.request_count == 2
    assert budget.requests_used == 2


@pytest.mark.asyncio
async def test_runtime_enforces_request_limit() -> None:
    """请求数达到预算上限后，运行时拒绝新的模型调用。"""

    runtime = AgentRuntime(budget=Budget(seconds=60, max_requests=1))
    await runtime.run_expert(Expert(), make_context())
    await runtime.run_expert(Expert(), make_context())

    assert runtime.request_count == 0


@pytest.mark.asyncio
async def test_shared_budget_reserves_request_before_parallel_model_call(tmp_path) -> None:
    """共享预算只剩一次请求时，并发 Runtime 不得都进入模型。"""

    shared = tmp_path / "shared.md"
    role_prompt = tmp_path / "role.md"
    shared.write_text("共享规则", encoding="utf-8")
    role_prompt.write_text("角色提示", encoding="utf-8")
    sources = [PromptSource("shared", shared), PromptSource("role", role_prompt)]
    budget = Budget(seconds=60, max_requests=1)
    first_model = ReservationBarrierModel()
    first_runtime = AgentRuntime(config=Config(llm_max_retries=0))
    second_model = TestModel(custom_output_args={"summary": "不应执行", "budget_seconds": 1})
    second_runtime = AgentRuntime(config=Config(llm_max_retries=0))
    first_task = asyncio.create_task(
        first_runtime.run_structured(
            first_model,
            role="defect",
            sources=sources,
            skills=[],
            dynamic_context="第一个并发调用",
            budget=budget,
            output_type=ReviewPlan,
        )
    )
    await asyncio.wait_for(first_model.started.wait(), timeout=0.5)

    second_error: BaseException | None = None
    try:
        await second_runtime.run_structured(
            second_model,
            role="verifier",
            sources=sources,
            skills=[],
            dynamic_context="第二个并发调用",
            budget=budget,
            output_type=ReviewPlan,
        )
    except BaseException as error:
        second_error = error
    finally:
        first_model.release.set()
    result = (await asyncio.gather(first_task, return_exceptions=True))[0]

    assert isinstance(second_error, RuntimeError)
    assert "预算上限" in str(second_error)
    assert isinstance(result, ReviewPlan)
    assert result.summary == "屏障完成"
    assert first_model.request_calls == 1
    assert second_runtime.request_count == 0
    assert budget.requests_used == 1


@pytest.mark.asyncio
async def test_agent_constructor_failure_releases_reservation_for_next_call(tmp_path, monkeypatch) -> None:
    """Agent 初始化异常未发出请求时，必须释放全部预留额度。"""

    import reviewcrew.agents.base as agent_base

    shared = tmp_path / "shared.md"
    role_prompt = tmp_path / "role.md"
    shared.write_text("共享规则", encoding="utf-8")
    role_prompt.write_text("角色提示", encoding="utf-8")
    sources = [PromptSource("shared", shared), PromptSource("role", role_prompt)]
    budget = Budget(seconds=60, max_requests=1)
    runtime = AgentRuntime(config=Config(llm_max_retries=0))
    original_agent = agent_base.Agent

    def fail_agent_construction(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("测试 Agent 构造失败")

    monkeypatch.setattr(agent_base, "Agent", fail_agent_construction)
    with pytest.raises(ValueError, match="构造失败"):
        await runtime.run_structured(
            TestModel(custom_output_args={"summary": "不会执行", "budget_seconds": 1}),
            role="verifier",
            sources=sources,
            skills=[],
            dynamic_context="构造失败路径",
            budget=budget,
            output_type=ReviewPlan,
        )

    assert budget.requests_used == 0
    assert runtime.request_count == 0

    monkeypatch.setattr(agent_base, "Agent", original_agent)
    result = await runtime.run_structured(
        TestModel(custom_output_args={"summary": "后续可用", "budget_seconds": 1}),
        role="verifier",
        sources=sources,
        skills=[],
        dynamic_context="恢复后的调用",
        budget=budget,
        output_type=ReviewPlan,
    )

    assert result.summary == "后续可用"
    assert budget.requests_used == 1
    assert runtime.request_count == 1


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
        [make_context().model_copy(update={"files": ["src/core.py"]})],
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
    runtime = AgentRuntime(config=Config(llm_max_retries=2))
    plan = await TeamLeadAgent(model=model, runtime=runtime).plan(
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
    assert runtime.run_records[-1].output_schema == "ReviewPlan"


@pytest.mark.asyncio
async def test_runtime_assembles_prompt_in_fixed_order_and_records_only_hashes(tmp_path) -> None:
    """公共运行时按固定顺序组装 Prompt，并只记录可审计的脱敏元数据。"""

    shared = tmp_path / "shared.md"
    role = tmp_path / "role.md"
    shared.write_text("共享规则", encoding="utf-8")
    role.write_text("角色提示", encoding="utf-8")
    runtime = AgentRuntime(config=Config(llm_max_retries=3))
    registry = SkillRegistry(Path(__file__).parents[1] / "reviewcrew" / "skills")
    selected = registry.select("team_lead", ["security"], Budget(seconds=60))

    prompt = runtime.compose_prompt(
        sources=[PromptSource("shared", shared), PromptSource("role", role)],
        skills=selected,
        dynamic_context="ReviewPlan/Context/Mailbox",
        budget=Budget(seconds=60),
        output_schema="ReviewPlan",
    )

    record = runtime.run_records[-1]
    assert prompt.index("共享规则") < prompt.index("角色提示") < prompt.index("风险路由")
    assert record.prompt_file_hashes["shared"]
    assert record.skills[0][0] == "risk-routing"
    assert "共享规则" not in repr(record)


@pytest.mark.asyncio
async def test_team_lead_keeps_defect_route_when_model_omits_it() -> None:
    """普通 PR 的模型输出不能移除 Defect 基线路由。"""

    model = TestModel(
        custom_output_args={
            "summary": "计划",
            "risk_tags": [],
            "required_agents": ["intent"],
            "context_ids": [],
            "shards": {},
            "budget_seconds": 1,
        }
    )

    plan = await TeamLeadAgent(model=model).plan(
        PRData(provider="local", repository="demo", title="普通变更", base_sha="b", head_sha="h", files=[], raw_diff="+ value = 1"),
        [make_context()],
        Budget(seconds=60),
    )

    assert plan.required_agents == ["defect", "intent"]


@pytest.mark.asyncio
async def test_team_lead_expands_large_pr_semantic_shards_only_with_budget() -> None:
    """大 PR 仅在预算充足时扩展为按模块划分的语义分片。"""

    contexts = [
        make_context().model_copy(update={"id": "ctx-auth", "files": ["src/session.py"]}),
        make_context().model_copy(update={"id": "ctx-payment", "files": ["src/payment.py"]}),
    ]
    pr = PRData(
        provider="local",
        repository="demo",
        title="重构",
        base_sha="b",
        head_sha="h",
        files=[],
        raw_diff="+ value = 1\n" * 4_000,
    )

    expanded = await TeamLeadAgent().plan(pr, contexts, Budget(seconds=120))
    constrained = await TeamLeadAgent().plan(pr, contexts, Budget(seconds=30))

    assert set(expanded.shards) == {"defect:session", "defect:payment"}
    assert constrained.shards == {"defect": ["ctx-auth", "ctx-payment"]}


@pytest.mark.asyncio
async def test_runtime_runs_hooks_around_structured_model_call(tmp_path) -> None:
    """公共结构化路径在模型调用前后运行 Hook。"""

    shared = tmp_path / "shared.md"
    role = tmp_path / "role.md"
    shared.write_text("共享规则", encoding="utf-8")
    role.write_text("角色提示", encoding="utf-8")
    hooks = HookManager()
    observed: list[str] = []

    async def capture(context: HookContext) -> None:
        observed.append(context.role)

    hooks.register("before_agent", capture)
    hooks.register("after_agent", capture)
    runtime = AgentRuntime(hook_manager=hooks)
    output = await runtime.run_structured(
        TestModel(custom_output_args={"summary": "计划", "budget_seconds": 1}),
        role="team_lead",
        sources=[PromptSource("shared", shared), PromptSource("role", role)],
        skills=[],
        dynamic_context="上下文",
        budget=Budget(seconds=60),
        output_type=ReviewPlan,
    )

    assert isinstance(output, ReviewPlan)
    assert observed == ["team_lead", "team_lead"]
