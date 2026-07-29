"""Verifier 流式 watcher 与结构化裁决测试。"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic_ai.models.test import TestModel

from reviewcrew.agents.base import AgentRuntime
from reviewcrew.agents.verifier import VerifierAgent
from reviewcrew.schemas import Budget, Finding
from reviewcrew.team.blackboard import EvidenceBlackboard
from reviewcrew.team.mailbox import Mailbox
from reviewcrew.team.publisher import MessagePublisher


def make_finding(finding_id: str, *, confidence: float = 0.9) -> Finding:
    """构造 Verifier 所需的最小公开候选。"""

    return Finding(
        id=finding_id,
        producer="defect",
        category="security",
        severity="high",
        confidence=confidence,
        file="src/service.py",
        line_start=10,
        line_end=10,
        title="SQL 拼接可注入",
        description="外部输入被直接拼接到查询语句。",
        trigger_condition="攻击者控制 user_id 并触发查询。",
        impact="攻击者可能读取未授权数据。",
        reasoning_summary="修改行直接拼接外部输入。",
        evidence=[
            {
                "source": "diff",
                "file": "src/service.py",
                "start_line": 10,
                "end_line": 10,
                "description": "修改行直接拼接 user_id。",
                "content": '+ query = "SELECT * FROM users WHERE id = " + user_id',
            }
        ],
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )


def make_verdict(
    *,
    accepted: bool,
    verdict: str,
    confidence: float,
    reason: str,
) -> dict[str, Any]:
    """构造假模型返回的结构化裁决。"""

    return {
        "finding_id": "由 watcher 绑定真实候选",
        "accepted": accepted,
        "verdict": verdict,
        "confidence": confidence,
        "severity": "high" if accepted else None,
        "reason": reason,
        "final_finding": None,
    }


class SequencedVerdictModel(TestModel):
    """按请求顺序返回多阶段裁决。"""

    def __init__(self, *outputs: dict[str, Any]) -> None:
        super().__init__(custom_output_args=outputs[0])
        self.outputs = outputs
        self.request_calls = 0

    async def request(self, messages, model_settings, model_request_parameters):  # type: ignore[no-untyped-def]
        self.custom_output_args = self.outputs[min(self.request_calls, len(self.outputs) - 1)]
        self.request_calls += 1
        return await super().request(messages, model_settings, model_request_parameters)


async def publish_candidate(
    publisher: MessagePublisher,
    finding: Finding,
    *,
    sender: str = "defect:ctx-sql",
) -> None:
    """通过真实发布桥接发送候选。"""

    await publisher.publish(
        sender=sender,
        recipient="verifier",
        kind="candidate_finding",
        key=f"candidate:{finding.id}",
        payload={"finding": finding.model_dump(mode="json"), "context_id": "ctx-sql"},
        correlation_id=finding.id,
    )


async def finish_experts(publisher: MessagePublisher) -> None:
    """发送两个冻结专家角色的安全终态。"""

    for role in ("defect", "intent"):
        await publisher.publish(
            sender=f"{role}:ctx-sql",
            recipient="*",
            kind="agent_completed",
            key="completed",
            payload={"agent_id": f"{role}:ctx-sql", "role": role},
        )


async def wait_for_kind(blackboard: EvidenceBlackboard, kind: str) -> None:
    """在短窗口内等待真实协作消息出现。"""

    async with asyncio.timeout(1):
        while not blackboard.by_kind(kind):
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_watch_rejects_candidate_with_upstream_validation_as_false_positive(tmp_path) -> None:
    """存在上游保护的候选必须被假模型裁决为误报。"""

    mailbox = Mailbox(tmp_path, "run-upstream")
    blackboard = EvidenceBlackboard("run-upstream")
    publisher = MessagePublisher(mailbox=mailbox, blackboard=blackboard)
    model = TestModel(
        custom_output_args=make_verdict(
            accepted=False,
            verdict="false_positive",
            confidence=0.95,
            reason="上游类型校验拒绝所有非数字输入。",
        )
    )
    watcher = asyncio.create_task(
        VerifierAgent(model=model).watch(mailbox, blackboard, Budget(seconds=2))
    )
    await asyncio.sleep(0)

    await publish_candidate(publisher, make_finding("finding-upstream"))
    await finish_experts(publisher)
    verdicts = await watcher

    assert verdicts[0].finding_id == "finding-upstream"
    assert verdicts[0].accepted is False
    assert verdicts[0].verdict == "false_positive"
    assert verdicts[0].final_finding is None


@pytest.mark.asyncio
async def test_watch_confirms_reachable_candidate_before_experts_finish(tmp_path) -> None:
    """候选到达后必须立即验证，不能等待专家全部结束。"""

    mailbox = Mailbox(tmp_path, "run-reachable")
    blackboard = EvidenceBlackboard("run-reachable")
    publisher = MessagePublisher(mailbox=mailbox, blackboard=blackboard)
    model = TestModel(
        custom_output_args=make_verdict(
            accepted=True,
            verdict="confirmed",
            confidence=0.91,
            reason="外部输入可达修改行，且不存在保护分支。",
        )
    )
    watcher = asyncio.create_task(
        VerifierAgent(model=model).watch(mailbox, blackboard, Budget(seconds=2))
    )
    await asyncio.sleep(0)

    await publish_candidate(publisher, make_finding("finding-reachable"))
    await wait_for_kind(blackboard, "verdict")

    assert blackboard.by_kind("agent_completed") == []
    assert watcher.done() is False
    await finish_experts(publisher)
    verdicts = await watcher
    assert verdicts[0].accepted is True
    assert verdicts[0].verdict == "confirmed"
    assert verdicts[0].final_finding is not None
    assert verdicts[0].final_finding.id == "finding-reachable"


@pytest.mark.asyncio
async def test_watch_requests_evidence_once_and_consumes_response_before_deadline(tmp_path) -> None:
    """首次证据不足时只补证一次，并以响应执行第二次结构化裁决。"""

    mailbox = Mailbox(tmp_path, "run-evidence")
    mailbox.register("defect:ctx-sql")
    blackboard = EvidenceBlackboard("run-evidence")
    publisher = MessagePublisher(mailbox=mailbox, blackboard=blackboard)
    runtime = AgentRuntime()
    model = SequencedVerdictModel(
        make_verdict(
            accepted=False,
            verdict="insufficient_evidence",
            confidence=0.5,
            reason="缺少上游调用入口证据。",
        ),
        make_verdict(
            accepted=True,
            verdict="confirmed",
            confidence=0.88,
            reason="补证确认外部入口可达修改行。",
        ),
    )
    watcher = asyncio.create_task(
        VerifierAgent(model=model, runtime=runtime, evidence_deadline_seconds=0.5).watch(
            mailbox, blackboard, Budget(seconds=2, max_requests=2)
        )
    )
    await asyncio.sleep(0)
    await publish_candidate(publisher, make_finding("finding-needs-evidence"))

    request = await mailbox.receive_one("defect:ctx-sql", timeout=1)
    assert request.kind == "verification_request"
    await publisher.publish(
        sender="defect:ctx-sql",
        recipient="verifier",
        kind="evidence_response",
        key="evidence:finding-needs-evidence",
        correlation_id="finding-needs-evidence",
        payload={
            "finding_id": "finding-needs-evidence",
            "conclusion": "supported",
            "evidence": [make_finding("evidence-holder").evidence[0].model_dump(mode="json")],
            "summary": "调用入口将未校验的 user_id 传入修改行。",
        },
    )
    await finish_experts(publisher)
    verdicts = await watcher

    assert len(blackboard.by_kind("verification_request")) == 1
    assert runtime.request_count == 2
    assert verdicts[0].verdict == "confirmed"


@pytest.mark.asyncio
async def test_watch_rejects_final_confidence_below_threshold(tmp_path) -> None:
    """模型即使接受候选，最终置信度低于 0.6 也必须保守拒绝。"""

    mailbox = Mailbox(tmp_path, "run-low-confidence")
    blackboard = EvidenceBlackboard("run-low-confidence")
    publisher = MessagePublisher(mailbox=mailbox, blackboard=blackboard)
    model = TestModel(
        custom_output_args=make_verdict(
            accepted=True,
            verdict="likely",
            confidence=0.59,
            reason="可达性仍有不确定性。",
        )
    )
    watcher = asyncio.create_task(
        VerifierAgent(model=model).watch(mailbox, blackboard, Budget(seconds=2))
    )
    await asyncio.sleep(0)

    await publish_candidate(publisher, make_finding("finding-low"))
    await finish_experts(publisher)
    verdicts = await watcher

    assert verdicts[0].accepted is False
    assert verdicts[0].verdict == "insufficient_evidence"
    assert verdicts[0].final_finding is None


@pytest.mark.asyncio
async def test_watch_keeps_at_most_eight_accepted_findings(tmp_path) -> None:
    """流式候选超过上限时最终只保留八条已接受 Finding。"""

    mailbox = Mailbox(tmp_path, "run-limit")
    blackboard = EvidenceBlackboard("run-limit")
    publisher = MessagePublisher(mailbox=mailbox, blackboard=blackboard)
    model = TestModel(
        custom_output_args=make_verdict(
            accepted=True,
            verdict="confirmed",
            confidence=0.9,
            reason="候选可达且证据充分。",
        )
    )
    watcher = asyncio.create_task(
        VerifierAgent(model=model).watch(mailbox, blackboard, Budget(seconds=3, max_requests=9))
    )
    await asyncio.sleep(0)

    for index in range(9):
        await publish_candidate(publisher, make_finding(f"finding-{index}"))
    await finish_experts(publisher)
    verdicts = await watcher

    accepted = [item for item in verdicts if item.accepted]
    assert len(accepted) == 8
    assert all(item.final_finding is not None for item in accepted)


@pytest.mark.asyncio
async def test_cancelled_watch_publishes_only_failed_terminal(tmp_path) -> None:
    """外部取消必须发布一次失败终态并继续传播取消。"""

    mailbox = Mailbox(tmp_path, "run-cancel-verifier")
    blackboard = EvidenceBlackboard("run-cancel-verifier")
    task = asyncio.create_task(
        VerifierAgent().watch(mailbox, blackboard, Budget(seconds=2))
    )
    await asyncio.sleep(0.02)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    failed = [item for item in blackboard.by_kind("agent_failed") if item.sender == "verifier"]
    completed = [item for item in blackboard.by_kind("agent_completed") if item.sender == "verifier"]
    assert len(failed) == 1
    assert completed == []


@pytest.mark.asyncio
async def test_watch_timeout_returns_partial_verdicts_and_completed_terminal(tmp_path) -> None:
    """没有专家终态时，预算截止必须返回已有裁决并发布一次完成终态。"""

    mailbox = Mailbox(tmp_path, "run-timeout-verifier")
    blackboard = EvidenceBlackboard("run-timeout-verifier")

    verdicts = await VerifierAgent().watch(mailbox, blackboard, Budget(seconds=1))

    failed = [item for item in blackboard.by_kind("agent_failed") if item.sender == "verifier"]
    completed = [item for item in blackboard.by_kind("agent_completed") if item.sender == "verifier"]
    assert verdicts == []
    assert failed == []
    assert len(completed) == 1
    assert "时间预算" in completed[0].payload["warning"]
