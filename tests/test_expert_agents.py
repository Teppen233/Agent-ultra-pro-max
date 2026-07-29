"""缺陷与意图专家 Agent 的 Prompt 和协作契约测试。"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from reviewcrew.agents.base import AgentRuntime
from reviewcrew.schemas import AgentSnapshot, Budget, ContextPack, DiffHunk, TeamMessage
from reviewcrew.team.blackboard import EvidenceBlackboard
from reviewcrew.team.mailbox import Mailbox
from reviewcrew.team.publisher import MessagePublisher


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


def make_model(*, category: str, line: int, title: str) -> TestModel:
    """构造返回单个候选问题的 Pydantic AI 假模型。"""

    return TestModel(
        custom_output_args={
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
    )


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

    await DefectAgent(
        model=make_model(category="security", line=10, title="SQL 拼接可注入"),
        runtime=AgentRuntime(),
        collaboration_window_seconds=0.01,
    ).run(make_context(), mailbox=mailbox, blackboard=blackboard, budget=Budget(seconds=60))

    assert blackboard.by_kind("handoff_response")[0].correlation_id == "handoff-correlation"
    response = blackboard.by_kind("evidence_response")[0]
    assert response.correlation_id == "finding-security"
    assert response.payload["conclusion"] == "supported"


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
