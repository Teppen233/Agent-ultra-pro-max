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


EXPECTED_EXPERTS = {"defect:ctx-sql", "intent:ctx-sql"}


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


class BlockingVerdictModel(TestModel):
    """进入真实模型请求后等待取消，用于验证绝对截止。"""

    def __init__(self) -> None:
        super().__init__(
            custom_output_args=make_verdict(
                accepted=True,
                verdict="confirmed",
                confidence=0.9,
                reason="不应在截止后返回。",
            )
        )
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def request(self, messages, model_settings, model_request_parameters):  # type: ignore[no-untyped-def]
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()
        return await super().request(messages, model_settings, model_request_parameters)


class RecordingVerdictModel(TestModel):
    """记录实际模型输入，以验证必要上下文和审计脱敏边界。"""

    def __init__(self, output: dict[str, Any]) -> None:
        super().__init__(custom_output_args=output)
        self.recorded_inputs: list[str] = []

    async def request(self, messages, model_settings, model_request_parameters):  # type: ignore[no-untyped-def]
        self.recorded_inputs.append(repr(messages))
        return await super().request(messages, model_settings, model_request_parameters)


async def publish_candidate(
    publisher: MessagePublisher,
    finding: Finding,
    *,
    sender: str = "defect:ctx-sql",
    verification_context: list[dict[str, Any]] | None = None,
) -> None:
    """通过真实发布桥接发送候选。"""

    await publisher.publish(
        sender=sender,
        recipient="verifier",
        kind="candidate_finding",
        key=f"candidate:{finding.id}",
        payload={
            "finding": finding.model_dump(mode="json"),
            "context_id": "ctx-sql",
            "verification_context": verification_context or [],
        },
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
        VerifierAgent(model=model).watch(
            mailbox,
            blackboard,
            Budget(seconds=2),
            expected_agent_ids=EXPECTED_EXPERTS,
        )
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
async def test_watch_model_input_consumes_typed_protection_and_reachability_context(tmp_path) -> None:
    """Verifier 模型输入必须消费场景证据，而审计与消息不得落完整 Prompt。"""

    scenarios = [
        (
            "upstream",
            "上游仅允许数字 user_id，非法输入在调用前返回。",
            make_verdict(
                accepted=False,
                verdict="false_positive",
                confidence=0.95,
                reason="上游保护覆盖触发输入。",
            ),
        ),
        (
            "reachable",
            "公开路由把未经校验的 user_id 传入修改行。",
            make_verdict(
                accepted=True,
                verdict="confirmed",
                confidence=0.9,
                reason="外部入口可达修改行。",
            ),
        ),
    ]
    recorded: dict[str, str] = {}
    for name, description, output in scenarios:
        run_id = f"run-input-{name}"
        mailbox = Mailbox(tmp_path, run_id)
        blackboard = EvidenceBlackboard(run_id)
        publisher = MessagePublisher(mailbox=mailbox, blackboard=blackboard)
        runtime = AgentRuntime()
        model = RecordingVerdictModel(output)
        watcher = asyncio.create_task(
            VerifierAgent(model=model, runtime=runtime).watch(
                mailbox,
                blackboard,
                Budget(seconds=2),
                expected_agent_ids={"defect:ctx-sql"},
            )
        )
        await asyncio.sleep(0)
        await publish_candidate(
            publisher,
            make_finding("finding-input"),
            verification_context=[
                {
                    "source": "read_file_range",
                    "file": "src/service.py",
                    "start_line": 1,
                    "end_line": 8,
                    "description": description,
                    "content": "def route(user_id): ...",
                }
            ],
        )
        await publisher.publish(
            sender="defect:ctx-sql",
            recipient="*",
            kind="agent_completed",
            key="completed",
            payload={"agent_id": "defect:ctx-sql", "role": "defect"},
        )
        await watcher

        recorded[name] = model.recorded_inputs[0]
        assert description not in repr(runtime.run_records)
        persisted = (tmp_path / run_id / "mailbox.jsonl").read_text(encoding="utf-8")
        assert "你是 ReviewCrew 的代码审查系统" not in persisted
        assert "model_request_parameters" not in persisted

    assert scenarios[0][1] in recorded["upstream"]
    assert scenarios[1][1] not in recorded["upstream"]
    assert scenarios[1][1] in recorded["reachable"]
    assert scenarios[0][1] not in recorded["reachable"]


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
        VerifierAgent(model=model).watch(
            mailbox,
            blackboard,
            Budget(seconds=2),
            expected_agent_ids=EXPECTED_EXPERTS,
        )
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
        VerifierAgent(model=model, runtime=runtime, evidence_deadline_seconds=1).watch(
            mailbox,
            blackboard,
            Budget(seconds=2, max_requests=2),
            expected_agent_ids=EXPECTED_EXPERTS,
        )
    )
    await asyncio.sleep(0)
    await publish_candidate(publisher, make_finding("finding-needs-evidence"))

    request = await mailbox.receive_one("defect:ctx-sql", timeout=1)
    assert request.kind == "verification_request"
    assert request.payload["deadline_seconds"] == 1
    assert request.expires_at is not None
    assert 0.8 <= (request.expires_at - request.timestamp).total_seconds() <= 1.0
    await publisher.publish(
        sender="defect:ctx-sql",
        recipient="verifier",
        kind="evidence_response",
        key="evidence:finding-needs-evidence",
        correlation_id="finding-needs-evidence",
        payload={
            "finding_id": "finding-needs-evidence",
            "conclusion": "supported",
            "evidence": [
                make_finding("evidence-holder").evidence[0].model_dump(mode="json"),
                {
                    "source": "search_code",
                    "file": "src/service.py",
                    "start_line": 5,
                    "end_line": 5,
                    "description": "公开入口把 user_id 直接传入查询函数。",
                    "content": "return find_user(request.path_params['user_id'])",
                },
            ],
            "summary": "调用入口将未校验的 user_id 传入修改行。",
        },
    )
    await finish_experts(publisher)
    verdicts = await watcher

    assert len(blackboard.by_kind("verification_request")) == 1
    assert runtime.request_count == 2
    assert verdicts[0].verdict == "confirmed"
    assert verdicts[0].final_finding is not None
    assert [(item.source, item.start_line) for item in verdicts[0].final_finding.evidence] == [
        ("diff", 10),
        ("search_code", 5),
    ]


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
        VerifierAgent(model=model).watch(
            mailbox,
            blackboard,
            Budget(seconds=2),
            expected_agent_ids=EXPECTED_EXPERTS,
        )
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
        VerifierAgent(model=model).watch(
            mailbox,
            blackboard,
            Budget(seconds=3, max_requests=9),
            expected_agent_ids=EXPECTED_EXPERTS,
        )
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
async def test_watch_verifies_same_finding_id_only_once_across_shards(tmp_path) -> None:
    """不同分片重复发布同一 Finding 时不得重复调用模型、计数或返回裁决。"""

    mailbox = Mailbox(tmp_path, "run-idempotent-finding")
    blackboard = EvidenceBlackboard("run-idempotent-finding")
    publisher = MessagePublisher(mailbox=mailbox, blackboard=blackboard)
    runtime = AgentRuntime()
    model = TestModel(
        custom_output_args=make_verdict(
            accepted=True,
            verdict="confirmed",
            confidence=0.9,
            reason="候选可达且证据充分。",
        )
    )
    expected = {"defect:ctx-a", "defect:ctx-b"}
    watcher = asyncio.create_task(
        VerifierAgent(model=model, runtime=runtime).watch(
            mailbox,
            blackboard,
            Budget(seconds=2, max_requests=2),
            expected_agent_ids=expected,
        )
    )
    await asyncio.sleep(0)

    finding = make_finding("finding-shared")
    await publish_candidate(publisher, finding, sender="defect:ctx-a")
    await publish_candidate(publisher, finding, sender="defect:ctx-b")
    for agent_id in sorted(expected):
        await publisher.publish(
            sender=agent_id,
            recipient="*",
            kind="agent_completed",
            key="completed",
            payload={"agent_id": agent_id, "role": "defect"},
        )
    verdicts = await watcher

    assert runtime.request_count == 1
    assert len(verdicts) == 1
    assert verdicts[0].finding_id == "finding-shared"
    assert len(blackboard.by_kind("verdict")) == 1


@pytest.mark.asyncio
async def test_cancelled_watch_publishes_only_failed_terminal(tmp_path) -> None:
    """外部取消必须发布一次失败终态并继续传播取消。"""

    mailbox = Mailbox(tmp_path, "run-cancel-verifier")
    blackboard = EvidenceBlackboard("run-cancel-verifier")
    task = asyncio.create_task(
        VerifierAgent().watch(
            mailbox,
            blackboard,
            Budget(seconds=2),
            expected_agent_ids=EXPECTED_EXPERTS,
        )
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


@pytest.mark.asyncio
async def test_watch_deadline_cancels_blocked_model_and_returns_partial_verdict(tmp_path) -> None:
    """模型调用挂起时，绝对截止必须取消调用并保守返回部分结果。"""

    mailbox = Mailbox(tmp_path, "run-model-timeout")
    blackboard = EvidenceBlackboard("run-model-timeout")
    publisher = MessagePublisher(mailbox=mailbox, blackboard=blackboard)
    model = BlockingVerdictModel()
    watcher = asyncio.create_task(
        VerifierAgent(model=model).watch(
            mailbox,
            blackboard,
            Budget(seconds=1),
            expected_agent_ids={"defect:ctx-sql"},
        )
    )
    await asyncio.sleep(0)
    await publish_candidate(publisher, make_finding("finding-blocked"))
    await publisher.publish(
        sender="defect:ctx-sql",
        recipient="*",
        kind="agent_completed",
        key="completed",
        payload={"agent_id": "defect:ctx-sql", "role": "defect"},
    )
    await asyncio.wait_for(model.started.wait(), timeout=0.5)

    verdicts = await asyncio.wait_for(watcher, timeout=1.5)

    assert model.cancelled.is_set()
    assert len(verdicts) == 1
    assert verdicts[0].accepted is False
    assert verdicts[0].verdict == "insufficient_evidence"
    assert blackboard.by_kind("verification_request") == []
    completed = [item for item in blackboard.by_kind("agent_completed") if item.sender == "verifier"]
    failed = [item for item in blackboard.by_kind("agent_failed") if item.sender == "verifier"]
    assert len(completed) == 1
    assert "时间预算" in completed[0].payload["warning"]
    assert failed == []


@pytest.mark.asyncio
async def test_watch_stops_after_only_expected_agent_finishes(tmp_path) -> None:
    """只启动单个专家时，其实例终态必须让 watcher 正常收敛而非等待超时。"""

    mailbox = Mailbox(tmp_path, "run-single-agent")
    blackboard = EvidenceBlackboard("run-single-agent")
    publisher = MessagePublisher(mailbox=mailbox, blackboard=blackboard)
    watcher = asyncio.create_task(
        VerifierAgent().watch(
            mailbox,
            blackboard,
            Budget(seconds=2),
            expected_agent_ids={"defect:ctx-only"},
        )
    )
    await asyncio.sleep(0)

    await publisher.publish(
        sender="defect:ctx-only",
        recipient="*",
        kind="agent_completed",
        key="completed",
        payload={"agent_id": "defect:ctx-only", "role": "defect"},
    )
    verdicts = await asyncio.wait_for(watcher, timeout=0.5)

    assert verdicts == []
    terminal = [item for item in blackboard.by_kind("agent_completed") if item.sender == "verifier"]
    assert len(terminal) == 1
    assert "warning" not in terminal[0].payload


@pytest.mark.asyncio
async def test_watch_waits_for_every_expected_shard_instance(tmp_path) -> None:
    """同角色多分片时，任一实例未终止都不得让 watcher 提前退出。"""

    mailbox = Mailbox(tmp_path, "run-shards")
    blackboard = EvidenceBlackboard("run-shards")
    publisher = MessagePublisher(mailbox=mailbox, blackboard=blackboard)
    expected = {"defect:ctx-a", "defect:ctx-b", "intent:ctx-a"}
    watcher = asyncio.create_task(
        VerifierAgent().watch(
            mailbox,
            blackboard,
            Budget(seconds=2),
            expected_agent_ids=expected,
        )
    )
    await asyncio.sleep(0)

    for agent_id, role in (("defect:ctx-a", "defect"), ("intent:ctx-a", "intent")):
        await publisher.publish(
            sender=agent_id,
            recipient="*",
            kind="agent_completed",
            key="completed",
            payload={"agent_id": agent_id, "role": role},
        )
    await asyncio.sleep(0.02)
    assert watcher.done() is False

    await publisher.publish(
        sender="defect:ctx-b",
        recipient="*",
        kind="agent_completed",
        key="completed",
        payload={"agent_id": "defect:ctx-b", "role": "defect"},
    )
    assert await asyncio.wait_for(watcher, timeout=0.5) == []


@pytest.mark.asyncio
async def test_real_watcher_ignores_stop_until_expected_terminals_and_queued_candidate_are_consumed(tmp_path) -> None:
    """实例集合非空时，stop_event 不得跳过已排队候选和终态。"""

    mailbox = Mailbox(tmp_path, "run-stop-race")
    publisher = MessagePublisher(mailbox=mailbox, blackboard=None)
    finding = make_finding("finding-stop-race")
    await publish_candidate(publisher, finding)
    for agent_id in ("defect:ctx-a", "intent:ctx-b"):
        await publisher.publish(
            sender=agent_id,
            recipient="verifier",
            kind="agent_completed",
            key="completed",
            payload={"agent_id": agent_id, "role": agent_id.split(":", 1)[0]},
        )
    stop_event = asyncio.Event()
    stop_event.set()
    model = TestModel(custom_output_args=make_verdict(accepted=True, verdict="confirmed", confidence=0.9, reason="已验证"))

    verdicts = await VerifierAgent(model=model).watch(
        mailbox,
        EvidenceBlackboard("run-stop-race"),
        Budget(seconds=2),
        expected_agent_ids={"defect:ctx-a", "intent:ctx-b"},
        stop_event=stop_event,
    )

    assert [item.finding_id for item in verdicts] == [finding.id]


@pytest.mark.asyncio
async def test_watch_accepts_explicit_stop_event_without_expected_agents(tmp_path) -> None:
    """调用方未提供实例集合时，可用显式停止事件安全结束 watcher。"""

    mailbox = Mailbox(tmp_path, "run-explicit-stop")
    blackboard = EvidenceBlackboard("run-explicit-stop")
    stop_event = asyncio.Event()
    watcher = asyncio.create_task(
        VerifierAgent().watch(
            mailbox,
            blackboard,
            Budget(seconds=2),
            stop_event=stop_event,
        )
    )
    await asyncio.sleep(0)

    stop_event.set()

    assert await asyncio.wait_for(watcher, timeout=0.5) == []
