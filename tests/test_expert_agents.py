"""缺陷与意图专家 Agent 的 Prompt 和协作契约测试。"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.models.test import TestModel

from reviewcrew.agents.base import AgentRuntime
from reviewcrew.config import Config
from reviewcrew.schemas import AgentSnapshot, Budget, CodeEvidence, ContextPack, DiffHunk, TeamMessage
from reviewcrew.team.blackboard import EvidenceBlackboard
from reviewcrew.team.mailbox import Mailbox
from reviewcrew.team.publisher import MessagePublisher


def test_expert_uses_configured_collaboration_window_by_default() -> None:
    """未显式注入窗口时，专家采用配置上限而不是等待完整阶段预算。"""

    from reviewcrew.agents.defect import DefectAgent

    agent = DefectAgent(config=Config(llm_timeout_seconds=5, collaboration_window_seconds=7.5))

    assert agent._collaboration_window_seconds == 7.5


def make_context(*, sample_rate: bool = False) -> ContextPack:
    """构造包含 SQL 拼接或 falsy 采样率变更的最小上下文。"""

    changed_line = "if sample_rate:" if sample_rate else 'query = "SELECT * FROM users WHERE id = " + user_id'
    return ContextPack(
        id="ctx-sample" if sample_rate else "ctx-sql",
        repository="acme/demo",
        base_sha="base",
        head_sha="head",
        pr_title="调整查询与采样逻辑",
        pr_description="采样率为 0 时必须保留配置语义。",
        files=["src/service.py"],
        diff_hunks=[
            DiffHunk(
                id="hunk-1",
                file="src/service.py",
                old_start=10,
                old_count=1,
                new_start=10 if not sample_rate else 22,
                new_count=1,
                changed_lines=[10 if not sample_rate else 22],
                content=f"+ {changed_line}",
            )
        ],
    )


def make_snapshot_output(*, category: str, line: int, title: str) -> dict[str, Any]:
    """构造专家初审阶段的结构化输出。"""

    return {
        "agent_id": "fake",
        "findings": [
            {
                "id": f"finding-{category}",
                "producer": "defect",
                "category": category,
                "severity": "high",
                "confidence": 0.9,
                "file": "src/service.py",
                "line_start": line,
                "line_end": line,
                "title": title,
                "description": "变更后的行为会在可达输入下产生错误结果。",
                "trigger_condition": "外部输入触发该分支。",
                "impact": "请求可能失败或返回错误结果。",
                "reasoning_summary": "候选问题直接位于变更行。",
                "evidence": [
                    {
                        "source": "diff",
                        "file": "src/service.py",
                        "start_line": line,
                        "end_line": line,
                        "description": "变更行缺少必要约束。",
                        "content": "changed line",
                    }
                ],
                "created_at": datetime.now(UTC).isoformat(),
            }
        ],
        "completed_checks": ["合同测试"],
        "pending_checks": [],
        "warnings": [],
    }


def make_model(*, category: str, line: int, title: str) -> TestModel:
    """构造返回单个候选问题的 Pydantic AI 假模型。"""

    return TestModel(custom_output_args=make_snapshot_output(category=category, line=line, title=title))


def make_handoff_assessment(conclusion: str, reason: str) -> dict[str, Any]:
    """构造定向复查阶段的公开结构化结论。"""

    return {
        "conclusion": conclusion,
        "reason": reason,
        "evidence": [
            {
                "source": "diff",
                "file": "src/service.py",
                "start_line": 10,
                "end_line": 10,
                "description": "目标修改行直接拼接外部输入。",
                "content": '+ query = "SELECT * FROM users WHERE id = " + user_id',
            }
        ],
    }


class SequencedStructuredModel(TestModel):
    """按请求顺序返回专家快照与定向复查结果。"""

    def __init__(self, *outputs: dict[str, Any]) -> None:
        super().__init__(custom_output_args=outputs[0])
        self.outputs = outputs
        self.request_calls = 0

    async def request(self, messages, model_settings, model_request_parameters):  # type: ignore[no-untyped-def]
        self.custom_output_args = self.outputs[min(self.request_calls, len(self.outputs) - 1)]
        self.request_calls += 1
        return await super().request(messages, model_settings, model_request_parameters)


class CandidateBarrierPublisher:
    """在候选真实发布后唤醒并发请求生产者。"""

    def __init__(self, delegate: MessagePublisher) -> None:
        self.delegate = delegate
        self.candidate_published = asyncio.Event()

    async def publish(self, **kwargs) -> bool:  # type: ignore[no-untyped-def]
        published = await self.delegate.publish(**kwargs)
        if published and kwargs["kind"] == "candidate_finding":
            self.candidate_published.set()
        return published


class ImmediateVerifierTerminalPublisher:
    """专家发布初审屏障时同步广播 Verifier 终态，复现注册窗口竞态。"""

    def __init__(self, delegate: MessagePublisher) -> None:
        self.delegate = delegate

    async def publish(self, **kwargs) -> bool:  # type: ignore[no-untyped-def]
        published = await self.delegate.publish(**kwargs)
        if published and kwargs["kind"] == "agent_review_completed":
            await self.delegate.publish(
                sender="verifier",
                recipient="*",
                kind="agent_completed",
                key="completed",
                payload={"agent_id": "verifier", "role": "verifier"},
            )
        return published


def test_expert_prompts_cover_required_review_dimensions() -> None:
    """两个角色 Prompt 必须显式列出各自不可省略的审查维度。"""

    prompt_root = Path(__file__).parents[1] / "reviewcrew" / "agents" / "prompts"
    defect_prompt = (prompt_root / "defect.md").read_text(encoding="utf-8")
    intent_prompt = (prompt_root / "intent.md").read_text(encoding="utf-8")

    for keyword in ("静态", "安全", "内存", "资源"):
        assert keyword in defect_prompt
    for keyword in ("意图总结", "行为总结", "偏差比较", "边界", "架构"):
        assert keyword in intent_prompt


@pytest.mark.asyncio
async def test_defect_agent_publishes_sql_injection_candidate_from_fake_model(tmp_path) -> None:
    """Defect Agent 将 SQL 拼接候选以正确类别和修改行发布。"""

    from reviewcrew.agents.defect import DefectAgent

    mailbox = Mailbox(tmp_path, "run-expert")
    blackboard = EvidenceBlackboard("run-expert")
    snapshot = await DefectAgent(
        model=make_model(category="security", line=10, title="SQL 拼接可注入"),
        runtime=AgentRuntime(),
        collaboration_window_seconds=0.01,
    ).run(make_context(), mailbox=mailbox, blackboard=blackboard, budget=Budget(seconds=60))

    assert snapshot.findings[0].category == "security"
    assert snapshot.findings[0].line_start == 10
    candidates = blackboard.by_kind("candidate_finding")
    assert candidates[0].payload["finding"]["id"] == "finding-security"
    assert blackboard.by_kind("agent_completed")


@pytest.mark.asyncio
async def test_expert_terminal_message_exposes_safe_check_progress(tmp_path) -> None:
    """专家终态必须携带可公开的检查进度，避免前端只剩三个裸计数。"""

    from reviewcrew.agents.defect import DefectAgent

    mailbox = Mailbox(tmp_path, "run-check-progress")
    blackboard = EvidenceBlackboard("run-check-progress")

    await DefectAgent(
        model=make_model(category="security", line=10, title="SQL 拼接可注入"),
        collaboration_window_seconds=0.01,
    ).run(make_context(), mailbox=mailbox, blackboard=blackboard, budget=Budget(seconds=60))

    terminal = blackboard.by_kind("agent_completed")[0]
    assert terminal.payload["context_id"] == "ctx-sql"
    assert terminal.payload["completed_checks"] == [
        "静态破坏",
        "安全输入",
        "内存与资源生命周期",
        "合同测试",
    ]
    assert terminal.payload["pending_checks"] == []


@pytest.mark.asyncio
async def test_expert_publishes_bounded_typed_context_for_verifier(tmp_path) -> None:
    """专家候选携带去重且有上限的类型化上下文，供 Verifier 判断可达性。"""

    from reviewcrew.agents.defect import DefectAgent

    evidence = CodeEvidence(
        source="enclosing_code",
        file="src/service.py",
        start_line=1,
        end_line=20,
        description="公开入口直接调用修改函数。",
        content="def public_api(user_id): return load_user(user_id)",
    )
    context = make_context().model_copy(
        update={
            "enclosing_code": [evidence, evidence],
            "related_code": [
                evidence.model_copy(update={"source": "related_code", "start_line": index, "end_line": index})
                for index in range(21, 35)
            ],
        }
    )
    mailbox = Mailbox(tmp_path, "run-verification-context")
    blackboard = EvidenceBlackboard("run-verification-context")

    await DefectAgent(
        model=make_model(category="security", line=10, title="SQL 拼接可注入"),
        collaboration_window_seconds=0.01,
    ).run(context, mailbox=mailbox, blackboard=blackboard, budget=Budget(seconds=60))

    payload = blackboard.by_kind("candidate_finding")[0].payload
    verification_context = payload["verification_context"]
    assert len(verification_context) == 12
    assert verification_context[0]["source"] == "enclosing_code"
    assert len({(item["source"], item["file"], item["start_line"], item["end_line"]) for item in verification_context}) == 12


@pytest.mark.asyncio
async def test_intent_agent_publishes_falsy_sample_rate_candidate_from_fake_model(tmp_path) -> None:
    """Intent Agent 将被跳过的 ``sample_rate=0.0`` 语义候选发布到修改行。"""

    from reviewcrew.agents.intent import IntentAgent

    mailbox = Mailbox(tmp_path, "run-expert")
    blackboard = EvidenceBlackboard("run-expert")
    snapshot = await IntentAgent(
        model=make_model(category="logic", line=22, title="零采样率被错误跳过"),
        runtime=AgentRuntime(),
        collaboration_window_seconds=0.01,
    ).run(make_context(sample_rate=True), mailbox=mailbox, blackboard=blackboard, budget=Budget(seconds=60))

    assert snapshot.findings[0].category == "logic"
    assert snapshot.findings[0].line_start == 22
    assert blackboard.by_kind("candidate_finding")[0].payload["finding"]["id"] == "finding-logic"
    assert blackboard.by_kind("agent_completed")


@pytest.mark.asyncio
async def test_expert_responds_to_structured_handoff_and_evidence_request(tmp_path) -> None:
    """专家最多处理两次移交，并以结构化证据回应定向补证请求。"""

    from reviewcrew.agents.defect import DefectAgent

    mailbox = Mailbox(tmp_path, "run-expert")
    blackboard = EvidenceBlackboard("run-expert")
    now = datetime.now(UTC)
    blackboard.apply(
        TeamMessage(
            id="handoff-1",
            run_id="run-expert",
            sequence=1,
            timestamp=now,
            sender="intent:ctx-sql",
            recipient="defect:ctx-sql",
            kind="handoff_request",
            correlation_id="handoff-correlation",
            payload={
                "source_agent": "intent:ctx-sql",
                "target_agent": "defect",
                "hypothesis": "确认 SQL 查询是否直接使用外部输入。",
                "file": "src/service.py",
                "lines": [10],
                "requested_check": "检查注入汇点。",
                "evidence": [],
            },
        )
    )
    blackboard.apply(
        TeamMessage(
            id="evidence-1",
            run_id="run-expert",
            sequence=2,
            timestamp=now,
            sender="verifier",
            recipient="defect:ctx-sql",
            kind="verification_request",
            correlation_id="finding-security",
            payload={
                "finding_id": "finding-security",
                "target_agent": "defect",
                "question": "提供变更行证据。",
                "required_evidence": ["diff"],
                "deadline_seconds": 30,
            },
        )
    )

    runtime = AgentRuntime()
    model = SequencedStructuredModel(
        make_snapshot_output(category="security", line=10, title="SQL 拼接可注入"),
        make_handoff_assessment("supported", "目标行直接拼接外部输入，支持注入风险假设。"),
    )
    await DefectAgent(
        model=model,
        runtime=runtime,
        collaboration_window_seconds=0.01,
    ).run(make_context(), mailbox=mailbox, blackboard=blackboard, budget=Budget(seconds=60))

    handoff = blackboard.by_kind("handoff_response")[0]
    assert handoff.correlation_id == "handoff-correlation"
    assert handoff.payload["conclusion"] == "supported"
    assert handoff.payload["reason"] == "目标行直接拼接外部输入，支持注入风险假设。"
    assert runtime.request_count == 2
    assert [record.output_schema for record in runtime.run_records] == ["AgentSnapshot", "HandoffAssessment"]
    response = blackboard.by_kind("evidence_response")[0]
    assert response.correlation_id == "finding-security"
    assert response.payload["conclusion"] == "supported"


@pytest.mark.asyncio
async def test_expert_answers_each_finding_once_up_to_evidence_request_limit(tmp_path) -> None:
    """专家按 Finding 去重补证请求，并遵守单分片总响应上限。"""

    from reviewcrew.agents.defect import DefectAgent

    mailbox = Mailbox(tmp_path, "run-evidence-limit")
    blackboard = EvidenceBlackboard("run-evidence-limit")
    now = datetime.now(UTC)
    requested_ids = ["finding-security", "finding-security-2", "finding-security", "finding-security-3"]
    for sequence, finding_id in enumerate(requested_ids, start=1):
        blackboard.apply(
            TeamMessage(
                id=f"evidence-limit-{sequence}",
                run_id="run-evidence-limit",
                sequence=sequence,
                timestamp=now,
                sender="verifier",
                recipient="defect:ctx-sql",
                kind="verification_request",
                correlation_id=finding_id,
                payload={
                    "finding_id": finding_id,
                    "target_agent": "defect",
                    "question": "补充当前候选的修改行证据。",
                    "required_evidence": ["diff"],
                    "deadline_seconds": 30,
                },
            )
        )
    output = make_snapshot_output(category="security", line=10, title="SQL 拼接可注入")
    template = output["findings"][0]
    output["findings"].extend(
        [
            {**template, "id": "finding-security-2", "title": "第二个候选"},
            {**template, "id": "finding-security-3", "title": "第三个候选"},
        ]
    )

    await DefectAgent(
        model=TestModel(custom_output_args=output),
        collaboration_window_seconds=0.01,
        max_evidence_requests=2,
    ).run(
        make_context(),
        mailbox=mailbox,
        blackboard=blackboard,
        budget=Budget(seconds=1, max_requests=1),
    )

    responses = blackboard.by_kind("evidence_response")
    assert [item.payload["finding_id"] for item in responses] == [
        "finding-security",
        "finding-security-2",
    ]


@pytest.mark.asyncio
async def test_handoff_recheck_distinguishes_opposite_hypotheses_on_same_line(tmp_path) -> None:
    """同一目标行上的相反假设必须经过复查并得到不同结论。"""

    from reviewcrew.agents.defect import DefectAgent

    mailbox = Mailbox(tmp_path, "run-opposite")
    blackboard = EvidenceBlackboard("run-opposite")
    now = datetime.now(UTC)
    for sequence, hypothesis in enumerate(("该行存在 SQL 注入。", "该行不存在 SQL 注入。"), start=1):
        blackboard.apply(
            TeamMessage(
                id=f"handoff-opposite-{sequence}",
                run_id="run-opposite",
                sequence=sequence,
                timestamp=now,
                sender="intent:ctx-sql",
                recipient="defect:ctx-sql",
                kind="handoff_request",
                payload={
                    "source_agent": "intent:ctx-sql",
                    "target_agent": "defect",
                    "hypothesis": hypothesis,
                    "file": "src/service.py",
                    "lines": [10],
                    "requested_check": "检查 user_id 是否未经参数化直接进入 SQL。",
                    "evidence": [],
                },
            )
        )
    runtime = AgentRuntime()
    model = SequencedStructuredModel(
        make_snapshot_output(category="security", line=10, title="SQL 拼接可注入"),
        make_handoff_assessment("supported", "拼接外部输入支持存在注入风险。"),
        make_handoff_assessment("unsupported", "同一证据与不存在注入风险的假设相矛盾。"),
    )

    await DefectAgent(model=model, runtime=runtime, collaboration_window_seconds=0.01).run(
        make_context(), mailbox=mailbox, blackboard=blackboard, budget=Budget(seconds=60, max_requests=3)
    )

    responses = blackboard.by_kind("handoff_response")
    assert [item.payload["conclusion"] for item in responses] == ["supported", "unsupported"]
    assert runtime.request_count == 3


@pytest.mark.asyncio
async def test_handoff_returns_insufficient_when_shared_request_budget_is_exhausted(tmp_path) -> None:
    """共享请求预算只够初审时，移交必须降级并快速收敛。"""

    from reviewcrew.agents.defect import DefectAgent

    mailbox = Mailbox(tmp_path, "run-budget")
    blackboard = EvidenceBlackboard("run-budget")
    blackboard.apply(
        TeamMessage(
            id="handoff-budget",
            run_id="run-budget",
            sequence=1,
            timestamp=datetime.now(UTC),
            sender="intent:ctx-sql",
            recipient="defect:ctx-sql",
            kind="handoff_request",
            payload={
                "source_agent": "intent:ctx-sql",
                "target_agent": "defect",
                "hypothesis": "该行存在 SQL 注入。",
                "file": "src/service.py",
                "lines": [10],
                "requested_check": "检查 user_id 是否未经参数化直接进入 SQL。",
                "evidence": [],
            },
        )
    )
    runtime = AgentRuntime()

    await DefectAgent(
        model=make_model(category="security", line=10, title="SQL 拼接可注入"),
        runtime=runtime,
        collaboration_window_seconds=0.01,
    ).run(make_context(), mailbox=mailbox, blackboard=blackboard, budget=Budget(seconds=1, max_requests=1))

    response = blackboard.by_kind("handoff_response")[0]
    assert response.payload["conclusion"] == "insufficient"
    assert "预算" in response.payload["reason"]
    assert runtime.request_count == 1
    assert blackboard.by_kind("agent_completed")


@pytest.mark.asyncio
async def test_default_collaboration_deadline_handles_handoff_arriving_after_candidate(tmp_path) -> None:
    """候选发布后的真实迟到移交仍须在共享绝对截止时间内处理。"""

    from reviewcrew.agents.defect import DefectAgent

    mailbox = Mailbox(tmp_path, "run-late")
    blackboard = EvidenceBlackboard("run-late")
    delegate = MessagePublisher(mailbox=mailbox, blackboard=blackboard)
    publisher = CandidateBarrierPublisher(delegate)
    runtime = AgentRuntime()
    model = SequencedStructuredModel(
        make_snapshot_output(category="security", line=10, title="SQL 拼接可注入"),
        make_handoff_assessment("supported", "目标行直接拼接外部输入。"),
    )

    async def publish_late_handoff() -> None:
        await publisher.candidate_published.wait()
        await asyncio.sleep(0.30)
        await delegate.publish(
            sender="intent:ctx-sql",
            recipient="defect:ctx-sql",
            kind="handoff_request",
            key="late-handoff",
            payload={
                "source_agent": "intent:ctx-sql",
                "target_agent": "defect",
                "hypothesis": "该行存在 SQL 注入。",
                "file": "src/service.py",
                "lines": [10],
                "requested_check": "检查 user_id 是否未经参数化直接进入 SQL。",
                "evidence": [],
            },
        )

    producer = asyncio.create_task(publish_late_handoff())
    await DefectAgent(model=model, runtime=runtime, publisher=publisher).run(
        make_context(), mailbox=mailbox, blackboard=blackboard, budget=Budget(seconds=1, max_requests=2)
    )
    await producer

    response = blackboard.by_kind("handoff_response")[0]
    assert response.payload["conclusion"] == "supported"
    assert response.correlation_id == "intent:ctx-sql:late-handoff"


@pytest.mark.asyncio
async def test_runtime_accepts_expert_snapshot_from_both_experts() -> None:
    """公共 Runtime 必须直接消费两个专家的 AgentSnapshot。"""

    from reviewcrew.agents.defect import DefectAgent
    from reviewcrew.agents.intent import IntentAgent

    runtime = AgentRuntime()
    defect = DefectAgent(model=make_model(category="security", line=10, title="SQL 拼接"), runtime=runtime)
    intent = IntentAgent(model=make_model(category="logic", line=22, title="零值跳过"), runtime=runtime)

    defect_snapshot = await runtime.run_expert(defect, make_context())
    intent_snapshot = await runtime.run_expert(intent, make_context(sample_rate=True))

    assert isinstance(defect_snapshot, AgentSnapshot)
    assert defect_snapshot.findings[0].producer == "defect"
    assert intent_snapshot.findings[0].producer == "intent"


@pytest.mark.asyncio
async def test_publisher_assigns_unique_sequences_under_concurrency(tmp_path) -> None:
    """共享发布桥接必须原子地分配唯一序号。"""

    mailbox = Mailbox(tmp_path, "run-sequence")
    blackboard = EvidenceBlackboard("run-sequence")
    publisher = MessagePublisher(mailbox=mailbox, blackboard=blackboard)

    await asyncio.gather(
        *(
            publisher.publish(sender=f"defect:ctx-{index}", recipient="*", kind="agent_completed", key=str(index), payload={})
            for index in range(8)
        )
    )

    assert [message.sequence for message in blackboard.messages] == list(range(1, 9))


@pytest.mark.asyncio
async def test_expert_rejects_candidate_without_intersecting_diff_evidence(tmp_path) -> None:
    """候选定位正确但证据不来自修改行时不得发布。"""

    from reviewcrew.agents.defect import DefectAgent

    model = make_model(category="security", line=10, title="错误证据")
    model.custom_output_args["findings"][0]["evidence"][0].update(
        {"source": "read_file_range", "file": "other.py", "start_line": 1, "end_line": 1}
    )
    mailbox = Mailbox(tmp_path, "run-evidence")
    blackboard = EvidenceBlackboard("run-evidence")

    snapshot = await DefectAgent(model=model, collaboration_window_seconds=0.01).run(make_context(), mailbox=mailbox, blackboard=blackboard)

    assert snapshot.findings == []
    assert blackboard.by_kind("candidate_finding") == []


@pytest.mark.asyncio
async def test_cancelled_expert_publishes_only_failed_terminal(tmp_path) -> None:
    """取消在协作窗口内发生时必须发布一次失败终态并继续传播取消。"""

    from reviewcrew.agents.defect import DefectAgent

    mailbox = Mailbox(tmp_path, "run-cancel")
    blackboard = EvidenceBlackboard("run-cancel")
    task = asyncio.create_task(
        DefectAgent(collaboration_window_seconds=1.0).run(make_context(), mailbox=mailbox, blackboard=blackboard)
    )
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(blackboard.by_kind("agent_failed")) == 1
    assert blackboard.by_kind("agent_completed") == []


@pytest.mark.asyncio
async def test_expert_waits_for_verifier_after_announcing_initial_review_complete(tmp_path) -> None:
    """专家先声明候选发布完毕，收到 Verifier 终态后立即结束协作等待。"""

    from reviewcrew.agents.defect import DefectAgent

    mailbox = Mailbox(tmp_path, "run-review-barrier")
    blackboard = EvidenceBlackboard("run-review-barrier")
    publisher = MessagePublisher(mailbox=mailbox, blackboard=blackboard)
    task = asyncio.create_task(
        DefectAgent(collaboration_window_seconds=1.0).run(
            make_context(), mailbox=mailbox, blackboard=blackboard
        )
    )
    async with asyncio.timeout(0.2):
        while not blackboard.by_kind("agent_review_completed"):
            await asyncio.sleep(0)
    assert not task.done()

    await publisher.publish(
        sender="verifier",
        recipient="*",
        kind="agent_completed",
        key="completed",
        payload={"agent_id": "verifier", "role": "verifier"},
    )

    await asyncio.wait_for(task, timeout=0.2)
    assert len(blackboard.by_kind("agent_completed")) == 2


@pytest.mark.asyncio
async def test_expert_cannot_miss_verifier_terminal_during_review_barrier(tmp_path) -> None:
    """Verifier 在屏障发布期间完成时，专家也必须立即结束而非等满窗口。"""

    from reviewcrew.agents.defect import DefectAgent

    mailbox = Mailbox(tmp_path, "run-review-barrier-race")
    blackboard = EvidenceBlackboard("run-review-barrier-race")
    publisher = ImmediateVerifierTerminalPublisher(
        MessagePublisher(mailbox=mailbox, blackboard=blackboard)
    )

    await asyncio.wait_for(
        DefectAgent(publisher=publisher, collaboration_window_seconds=1.0).run(
            make_context(), mailbox=mailbox, blackboard=blackboard
        ),
        timeout=0.2,
    )

    assert blackboard.by_kind("agent_review_completed")
    assert any(
        message.payload.get("agent_id") == "verifier"
        for message in blackboard.by_kind("agent_completed")
    )


@pytest.mark.asyncio
async def test_cancelled_real_expert_publishes_snapshot_before_unique_failed_terminal(tmp_path) -> None:
    """真实专家在预算取消边界先发布安全快照，再发布唯一失败终态。"""

    from reviewcrew.agents.defect import DefectAgent

    class BlockingDefect(DefectAgent):
        async def _review(self, context, agent_id, budget):  # type: ignore[no-untyped-def]
            await asyncio.Future()

    mailbox = Mailbox(tmp_path, "run-budget-snapshot")
    blackboard = EvidenceBlackboard("run-budget-snapshot")
    task = asyncio.create_task(BlockingDefect().run(make_context(), mailbox=mailbox, blackboard=blackboard))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(blackboard.by_kind("agent_snapshot")) == 1
    assert blackboard.by_kind("agent_snapshot")[0].payload["snapshot"]["agent_id"] == "defect:ctx-sql"
    assert len(blackboard.by_kind("agent_failed")) == 1
