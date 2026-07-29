"""Orchestrator 并发状态机、降级和持久化测试。"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reviewcrew.config import Config
from reviewcrew.pipeline.orchestrator import Orchestrator
from reviewcrew.report import persist_report
from reviewcrew.schemas import (
    AgentSnapshot,
    Budget,
    CodeEvidence,
    ContextPack,
    Finding,
    PRData,
    ReviewPlan,
    ReviewRequest,
    StaticSignal,
    Verdict,
)
from reviewcrew.team.publisher import MessagePublisher


def make_pr() -> PRData:
    """构造不依赖网络和真实仓库的 PR。"""

    return PRData(
        provider="local",
        repository="acme/demo",
        title="修复鉴权",
        base_sha="base123",
        head_sha="head456",
        files=[],
        raw_diff="+ return repository.get(resource_id)",
    )


def make_context() -> ContextPack:
    """构造最小专家上下文。"""

    return ContextPack(
        id="ctx-auth",
        repository="acme/demo",
        base_sha="base123",
        head_sha="head456",
        pr_title="修复鉴权",
        files=["src/auth.py"],
        diff_hunks=[],
    )


def make_finding(*, producer: str = "defect", confidence: float = 0.92) -> Finding:
    """构造可由 Fake Verifier 接受的候选。"""

    return Finding(
        id=f"finding-{producer}",
        producer=producer,
        category="security",
        severity="high",
        confidence=confidence,
        file="src/auth.py",
        line_start=10,
        line_end=10,
        title="缺少资源归属校验",
        description="接口可读取其他用户的资源。",
        trigger_condition="攻击者提交其他用户的资源标识。",
        impact="可能泄露数据。",
        reasoning_summary="仅供 Agent 内部结构化校验，不得持久化。",
        suggestion="读取前验证资源所属用户。",
        evidence=[
            CodeEvidence(
                source="diff",
                file="src/auth.py",
                start_line=10,
                end_line=10,
                description="修改行直接读取资源。",
                content="return repository.get(resource_id)",
            )
        ],
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )


class FakeLead:
    """记录规划发生顺序并返回两个专家路由。"""

    def __init__(self, timeline: list[str]) -> None:
        self.timeline = timeline

    async def plan(self, pr: PRData, contexts: list[ContextPack], budget: Budget) -> ReviewPlan:
        self.timeline.append("planned")
        return ReviewPlan(
            summary="并行审查",
            required_agents=["defect", "intent"],
            context_ids=[item.id for item in contexts],
            shards={"defect": [contexts[0].id], "intent": [contexts[0].id]},
            budget_seconds=budget.seconds,
        )


class PublishingExpert:
    """发布一个候选，并等待 Verifier 已经开始处理。"""

    def __init__(self, role: str, publisher, timeline: list[str], verified: asyncio.Event) -> None:
        self.role = role
        self.publisher = publisher
        self.timeline = timeline
        self.verified = verified

    async def run(self, context: ContextPack, **_: object) -> AgentSnapshot:
        self.timeline.append(f"{self.role}.started")
        finding = make_finding(producer=self.role)
        if self.role == "defect":
            await self.publisher.publish(
                sender=f"{self.role}:{context.id}",
                recipient="verifier",
                kind="candidate_finding",
                key=f"candidate:{finding.id}",
                payload={"finding": finding.model_dump(mode="json"), "context_id": context.id},
                correlation_id=finding.id,
            )
            await asyncio.wait_for(self.verified.wait(), timeout=1)
        else:
            await asyncio.wait_for(self.verified.wait(), timeout=1)
        self.timeline.append(f"{self.role}.completed")
        return AgentSnapshot(agent_id=f"{self.role}:{context.id}", findings=[finding])


class StreamingVerifier:
    """收到首个候选便裁决，并等待 Orchestrator 显式停止。"""

    def __init__(self, timeline: list[str], verified: asyncio.Event) -> None:
        self.timeline = timeline
        self.verified = verified

    async def watch(
        self,
        mailbox,
        blackboard,
        budget: Budget,
        *,
        expected_agent_ids: set[str],
        stop_event: asyncio.Event,
    ) -> list[Verdict]:
        self.timeline.append("verifier.started")
        mailbox.register("verifier")
        while True:
            message = await mailbox.receive_one("verifier", timeout=1)
            if message.kind != "candidate_finding":
                continue
            finding = Finding.model_validate(message.payload["finding"])
            self.timeline.append("verifier.candidate")
            self.verified.set()
            await stop_event.wait()
            return [
                Verdict(
                    finding_id=finding.id,
                    accepted=True,
                    verdict="confirmed",
                    confidence=0.95,
                    severity="high",
                    reason="Fake 证据充分。",
                    final_finding=finding.model_copy(update={"confidence": 0.95}),
                )
            ]


async def fake_loader(request: ReviewRequest, config: Config) -> PRData:
    """返回固定 PR。"""

    return make_pr()


async def fake_context_builder(pr: PRData, request: ReviewRequest, config: Config) -> list[ContextPack]:
    """返回固定上下文。"""

    return [make_context()]


@pytest.mark.asyncio
async def test_review_streams_first_candidate_before_experts_finish_and_persists_artifacts(tmp_path: Path) -> None:
    """Verifier 必须在专家完成前消费候选，且最终保存结果、报告和事件。"""

    timeline: list[str] = []
    verified = asyncio.Event()

    async def static_analyzer(pr: PRData, contexts: list[ContextPack]) -> list[StaticSignal]:
        timeline.append("static.started")
        await verified.wait()
        timeline.append("static.completed")
        return []

    orchestrator = Orchestrator(
        Config(runs_dir=tmp_path / "runs"),
        pr_loader=fake_loader,
        context_builder=fake_context_builder,
        team_lead=FakeLead(timeline),
        defect_factory=lambda publisher: PublishingExpert("defect", publisher, timeline, verified),
        intent_factory=lambda publisher: PublishingExpert("intent", publisher, timeline, verified),
        verifier_factory=lambda publisher: StreamingVerifier(timeline, verified),
        static_analyzer=static_analyzer,
    )

    result = await orchestrator.review(
        ReviewRequest(repo_path=str(tmp_path), base_ref="base", head_ref="head")
    )

    assert result.status == "completed"
    assert [item.id for item in result.findings] == ["finding-defect"]
    assert timeline.index("planned") < timeline.index("defect.started")
    assert timeline.index("planned") < timeline.index("intent.started")
    assert timeline.index("verifier.candidate") < timeline.index("defect.completed")
    assert timeline.index("verifier.candidate") < timeline.index("intent.completed")
    assert timeline.index("static.started") < timeline.index("defect.completed")
    run_dir = tmp_path / "runs" / result.run_id
    assert (run_dir / "result.json").is_file()
    assert (run_dir / "report.md").is_file()
    assert (run_dir / "events.jsonl").is_file()
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events[-2]["type"] == "report.generated"
    assert events[-1]["type"] == "review.completed"
    for stage in ("loading_pr", "building_context", "planning", "team_review", "reporting"):
        stage_events = [item["type"] for item in events if item["data"].get("stage") == stage]
        assert stage_events == ["stage.started", "stage.completed"]
    persisted = (run_dir / "result.json").read_text(encoding="utf-8")
    assert "reasoning_summary" not in persisted
    assert "Fake 证据充分" not in persisted
    run_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in run_dir.iterdir()
        if path.is_file()
    )
    for forbidden in ("reasoning_summary", "Prompt", "响应", "思维链"):
        assert forbidden not in run_text


class EmptyVerifier:
    """等待显式停止后返回空裁决。"""

    async def watch(self, mailbox, blackboard, budget: Budget, *, stop_event: asyncio.Event, **_: object) -> list[Verdict]:
        await stop_event.wait()
        return []


class FailingVerifier:
    """模拟 Verifier 独立失败。"""

    async def watch(self, mailbox, blackboard, budget: Budget, **_: object) -> list[Verdict]:
        raise RuntimeError("verifier boom")


class SnapshotExpert:
    """返回候选或模拟单专家失败。"""

    def __init__(self, role: str, finding: Finding | None = None, *, fail: bool = False) -> None:
        self.role = role
        self.finding = finding
        self.fail = fail

    async def run(self, context: ContextPack, **_: object) -> AgentSnapshot:
        if self.fail:
            raise RuntimeError("expert boom")
        return AgentSnapshot(
            agent_id=f"{self.role}:{context.id}",
            findings=[] if self.finding is None else [self.finding],
        )


@pytest.mark.asyncio
async def test_single_expert_failure_degrades_to_partial_without_losing_verified_result(tmp_path: Path) -> None:
    """一个专家失败时另一个专家与已验证结果仍必须保留。"""

    finding = make_finding()

    class AcceptingVerifier:
        async def watch(self, mailbox, blackboard, budget: Budget, *, stop_event: asyncio.Event, **_: object) -> list[Verdict]:
            await stop_event.wait()
            return [
                Verdict(
                    finding_id=finding.id,
                    accepted=True,
                    verdict="confirmed",
                    confidence=0.93,
                    severity="high",
                    reason="证据充分。",
                    final_finding=finding,
                )
            ]

    result = await Orchestrator(
        Config(runs_dir=tmp_path / "runs"),
        pr_loader=fake_loader,
        context_builder=fake_context_builder,
        team_lead=FakeLead([]),
        defect_factory=lambda publisher: SnapshotExpert("defect", finding),
        intent_factory=lambda publisher: SnapshotExpert("intent", fail=True),
        verifier_factory=lambda publisher: AcceptingVerifier(),
    ).review(ReviewRequest(repo_path=str(tmp_path), base_ref="base", head_ref="head"))

    assert result.status == "partial"
    assert [item.id for item in result.findings] == [finding.id]
    assert any("Intent 专家" in warning and "失败" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_verifier_failure_keeps_only_high_confidence_candidates_as_partial(tmp_path: Path) -> None:
    """Verifier 失败时只保留高置信候选，并明确标注未经完整验证。"""

    high = make_finding(confidence=0.91)
    low = make_finding(producer="intent", confidence=0.61)
    result = await Orchestrator(
        Config(runs_dir=tmp_path / "runs"),
        pr_loader=fake_loader,
        context_builder=fake_context_builder,
        team_lead=FakeLead([]),
        defect_factory=lambda publisher: SnapshotExpert("defect", high),
        intent_factory=lambda publisher: SnapshotExpert("intent", low),
        verifier_factory=lambda publisher: FailingVerifier(),
    ).review(ReviewRequest(repo_path=str(tmp_path), base_ref="base", head_ref="head"))

    assert result.status == "partial"
    assert [item.id for item in result.findings] == [high.id]
    assert any("Verifier" in warning and "未经完整验证" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_stage_timeout_returns_partial_result_and_failed_stage_event(tmp_path: Path) -> None:
    """阶段超时必须结束运行、生成中文警告并保存失败阶段事件。"""

    async def slow_context(pr: PRData, request: ReviewRequest, config: Config) -> list[ContextPack]:
        await asyncio.sleep(1)
        return [make_context()]

    result = await Orchestrator(
        Config(runs_dir=tmp_path / "runs"),
        pr_loader=fake_loader,
        context_builder=slow_context,
        stage_timeouts={"building_context": 0.01},
    ).review(ReviewRequest(repo_path=str(tmp_path), base_ref="base", head_ref="head"))

    assert result.status == "partial"
    assert any("上下文构建阶段超时" in warning for warning in result.warnings)
    events = Orchestrator.read_events(tmp_path / "runs", result.run_id)
    assert any(event.type == "stage.failed" and event.data.get("stage") == "building_context" for event in events)
    assert (tmp_path / "runs" / result.run_id / "report.md").is_file()


@pytest.mark.asyncio
async def test_global_watchdog_returns_partial_and_terminates_watcher(tmp_path: Path) -> None:
    """全局 watchdog 必须取消 watcher，并保留已到达的候选快照。"""

    cancelled = asyncio.Event()
    finding = make_finding(confidence=0.94)

    class HangingExpert(SnapshotExpert):
        async def run(self, context: ContextPack, **_: object) -> AgentSnapshot:
            await asyncio.sleep(1)
            return await super().run(context)

    class HangingVerifier:
        async def watch(self, mailbox, blackboard, budget: Budget, **_: object) -> list[Verdict]:
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

    result = await Orchestrator(
        Config(runs_dir=tmp_path / "runs"),
        pr_loader=fake_loader,
        context_builder=fake_context_builder,
        team_lead=FakeLead([]),
        defect_factory=lambda publisher: SnapshotExpert("defect", finding),
        intent_factory=lambda publisher: HangingExpert("intent"),
        verifier_factory=lambda publisher: HangingVerifier(),
        global_timeout_seconds=0.03,
    ).review(ReviewRequest(repo_path=str(tmp_path), base_ref="base", head_ref="head"))

    assert result.status == "partial"
    assert cancelled.is_set()
    assert [item.id for item in result.findings] == [finding.id]
    assert any("全局审查超时" in warning for warning in result.warnings)
    assert (tmp_path / "runs" / result.run_id / "events.jsonl").is_file()


@pytest.mark.asyncio
async def test_global_watchdog_keeps_verdict_published_before_watcher_is_cancelled(tmp_path: Path) -> None:
    """Verifier 已发布但尚未返回的裁决必须从 Blackboard 恢复。"""

    finding = make_finding(confidence=0.70)

    class PublishedVerdictThenHangs:
        def __init__(self, publisher) -> None:
            self.publisher = publisher

        async def watch(self, mailbox, blackboard, budget: Budget, **_: object) -> list[Verdict]:
            verdict = Verdict(
                finding_id=finding.id,
                accepted=True,
                verdict="confirmed",
                confidence=0.9,
                severity="high",
                reason="已完成验证。",
                final_finding=finding,
            )
            await self.publisher.publish(
                sender="verifier",
                recipient="*",
                kind="verdict",
                key=f"verdict:{finding.id}",
                payload={"verdict": verdict.model_dump(mode="json")},
                correlation_id=finding.id,
            )
            await asyncio.Future()
            return []

    class HangingExpert(SnapshotExpert):
        async def run(self, context: ContextPack, **_: object) -> AgentSnapshot:
            await asyncio.sleep(1)
            return await super().run(context)

    result = await Orchestrator(
        Config(runs_dir=tmp_path / "runs"),
        pr_loader=fake_loader,
        context_builder=fake_context_builder,
        team_lead=FakeLead([]),
        defect_factory=lambda publisher: SnapshotExpert("defect", finding),
        intent_factory=lambda publisher: HangingExpert("intent"),
        verifier_factory=lambda publisher: PublishedVerdictThenHangs(publisher),
        global_timeout_seconds=0.03,
    ).review(ReviewRequest(repo_path=str(tmp_path), base_ref="base", head_ref="head"))

    assert [item.id for item in result.findings] == [finding.id]


@pytest.mark.asyncio
async def test_returned_verdict_does_not_duplicate_already_published_pipeline_event(tmp_path: Path) -> None:
    """真实 watcher 的消息发布与返回值不得生成两条相同裁决事件。"""

    finding = make_finding()

    class PublishingVerifier:
        def __init__(self, publisher) -> None:
            self.publisher = publisher

        async def watch(self, mailbox, blackboard, budget: Budget, *, stop_event: asyncio.Event, **_: object) -> list[Verdict]:
            await stop_event.wait()
            verdict = Verdict(
                finding_id=finding.id,
                accepted=True,
                verdict="confirmed",
                confidence=0.9,
                severity="high",
                reason="证据充分。",
                final_finding=finding,
            )
            await self.publisher.publish(
                sender="verifier",
                recipient="*",
                kind="verdict",
                key=f"verdict:{finding.id}",
                payload={"verdict": verdict.model_dump(mode="json")},
                correlation_id=finding.id,
            )
            return [verdict]

    result = await Orchestrator(
        Config(runs_dir=tmp_path / "runs"),
        pr_loader=fake_loader,
        context_builder=fake_context_builder,
        team_lead=FakeLead([]),
        defect_factory=lambda publisher: SnapshotExpert("defect", finding),
        intent_factory=lambda publisher: SnapshotExpert("intent"),
        verifier_factory=lambda publisher: PublishingVerifier(publisher),
    ).review(ReviewRequest(repo_path=str(tmp_path), base_ref="base", head_ref="head"))

    events = Orchestrator.read_events(tmp_path / "runs", result.run_id)
    accepted = [event for event in events if event.type == "verifier.accepted"]
    assert len(accepted) == 1


@pytest.mark.asyncio
async def test_unknown_exception_text_is_not_persisted_in_warning(tmp_path: Path) -> None:
    """未知依赖异常可能含模型内容，Orchestrator 只能记录异常类型。"""

    async def unsafe_loader(request: ReviewRequest, config: Config) -> PRData:
        raise ValueError("完整 Prompt 与模型私密响应：sensitive-output")

    result = await Orchestrator(
        Config(runs_dir=tmp_path / "runs"),
        pr_loader=unsafe_loader,
    ).review(ReviewRequest(repo_path=str(tmp_path), base_ref="base", head_ref="head"))

    persisted = (tmp_path / "runs" / result.run_id / "result.json").read_text(encoding="utf-8")
    assert "sensitive-output" not in persisted
    assert "ValueError" in persisted


@pytest.mark.asyncio
async def test_multi_context_watcher_waits_for_late_candidate_from_every_planned_instance(tmp_path: Path) -> None:
    """实例级 watcher 必须等到计划中的全部分片结束，不能漏掉后到候选。"""

    contexts = [
        make_context().model_copy(update={"id": "ctx-fast"}),
        make_context().model_copy(update={"id": "ctx-late"}),
    ]
    fast_done = asyncio.Event()
    intent_runs: list[str] = []
    finding = make_finding()

    async def contexts_builder(pr: PRData, request: ReviewRequest, config: Config) -> list[ContextPack]:
        return contexts

    class ShardedLead:
        async def plan(self, pr: PRData, packs: list[ContextPack], budget: Budget) -> ReviewPlan:
            return ReviewPlan(
                summary="仅运行 Defect 两个分片",
                required_agents=["defect"],
                context_ids=[item.id for item in packs],
                shards={"defect": ["ctx-fast", "ctx-late"]},
                budget_seconds=budget.seconds,
            )

    class LateExpert:
        async def run(self, context: ContextPack, *, mailbox, blackboard, **_: object) -> AgentSnapshot:
            if context.id == "ctx-fast":
                fast_done.set()
                return AgentSnapshot(agent_id="defect:ctx-fast")
            await fast_done.wait()
            await asyncio.sleep(0.01)
            publisher = MessagePublisher(mailbox=mailbox, blackboard=blackboard)
            await publisher.publish(
                sender="defect:ctx-late",
                recipient="verifier",
                kind="candidate_finding",
                key=f"candidate:{finding.id}",
                payload={"finding": finding.model_dump(mode="json"), "context_id": context.id},
                correlation_id=finding.id,
            )
            return AgentSnapshot(agent_id="defect:ctx-late", findings=[finding])

    class InstanceWatcher:
        async def watch(
            self,
            mailbox,
            blackboard,
            budget: Budget,
            *,
            expected_agent_ids: set[str],
            stop_event: asyncio.Event,
        ) -> list[Verdict]:
            assert expected_agent_ids == {"defect:ctx-fast", "defect:ctx-late"}
            mailbox.register("verifier")
            candidate: Finding | None = None
            terminals: set[str] = set()
            while not expected_agent_ids.issubset(terminals):
                message = await mailbox.receive_one("verifier", timeout=1)
                if message.kind == "candidate_finding":
                    candidate = Finding.model_validate(message.payload["finding"])
                if message.kind in {"agent_completed", "agent_failed"}:
                    terminals.add(message.payload["agent_id"])
            assert candidate is not None
            return [
                Verdict(
                    finding_id=candidate.id,
                    accepted=True,
                    verdict="confirmed",
                    confidence=0.9,
                    severity="high",
                    reason="后到候选已验证。",
                    final_finding=candidate,
                )
            ]

    result = await Orchestrator(
        Config(runs_dir=tmp_path / "runs"),
        pr_loader=fake_loader,
        context_builder=contexts_builder,
        team_lead=ShardedLead(),
        defect_factory=lambda publisher: LateExpert(),
        intent_factory=lambda publisher: intent_runs.append("unexpected") or SnapshotExpert("intent"),
        verifier_factory=lambda publisher: InstanceWatcher(),
    ).review(ReviewRequest(repo_path=str(tmp_path), base_ref="base", head_ref="head"))

    assert [item.id for item in result.findings] == [finding.id]
    assert intent_runs == []


@pytest.mark.asyncio
async def test_legacy_watcher_without_instance_contract_is_rejected_instead_of_silently_degraded(tmp_path: Path) -> None:
    """缺少实例级参数的旧 watcher 必须显式失败，不能静默退回角色级收敛。"""

    class LegacyWatcher:
        async def watch(self, mailbox, blackboard, budget: Budget) -> list[Verdict]:
            return []

    result = await Orchestrator(
        Config(runs_dir=tmp_path / "runs"),
        pr_loader=fake_loader,
        context_builder=fake_context_builder,
        team_lead=FakeLead([]),
        defect_factory=lambda publisher: SnapshotExpert("defect"),
        intent_factory=lambda publisher: SnapshotExpert("intent"),
        verifier_factory=lambda publisher: LegacyWatcher(),
    ).review(ReviewRequest(repo_path=str(tmp_path), base_ref="base", head_ref="head"))

    assert result.status == "partial"
    assert any("Verifier" in warning and "失败" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_plan_shards_and_max_concurrency_control_actual_expert_work(tmp_path: Path) -> None:
    """只运行计划分片，且同时执行的专家不得超过 max_concurrency。"""

    contexts = [make_context().model_copy(update={"id": f"ctx-{index}"}) for index in range(4)]
    active = 0
    peak = 0
    runs: list[tuple[str, str]] = []

    async def contexts_builder(pr: PRData, request: ReviewRequest, config: Config) -> list[ContextPack]:
        return contexts

    class PlannedLead:
        async def plan(self, pr: PRData, packs: list[ContextPack], budget: Budget) -> ReviewPlan:
            return ReviewPlan(
                summary="受限并发",
                required_agents=["defect", "intent"],
                context_ids=[item.id for item in packs],
                shards={"defect": ["ctx-0", "ctx-1", "ctx-2"], "intent": ["ctx-3"]},
                budget_seconds=budget.seconds,
            )

    class CountingExpert:
        def __init__(self, role: str) -> None:
            self.role = role

        async def run(self, context: ContextPack, **_: object) -> AgentSnapshot:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            runs.append((self.role, context.id))
            await asyncio.sleep(0.02)
            active -= 1
            return AgentSnapshot(agent_id=f"{self.role}:{context.id}")

    result = await Orchestrator(
        Config(runs_dir=tmp_path / "runs", max_concurrency=2),
        pr_loader=fake_loader,
        context_builder=contexts_builder,
        team_lead=PlannedLead(),
        defect_factory=lambda publisher: CountingExpert("defect"),
        intent_factory=lambda publisher: CountingExpert("intent"),
        verifier_factory=lambda publisher: EmptyVerifier(),
    ).review(ReviewRequest(repo_path=str(tmp_path), base_ref="base", head_ref="head"))

    assert result.status == "completed"
    assert set(runs) == {("defect", "ctx-0"), ("defect", "ctx-1"), ("defect", "ctx-2"), ("intent", "ctx-3")}
    assert peak <= 2


@pytest.mark.asyncio
async def test_real_style_verifier_failure_publishes_one_terminal_event(tmp_path: Path) -> None:
    """watcher 自己发布失败终态后抛错时，Orchestrator 不得重复生成终态。"""

    class PublishingFailure:
        def __init__(self, publisher) -> None:
            self.publisher = publisher

        async def watch(self, mailbox, blackboard, budget: Budget, **_: object) -> list[Verdict]:
            await self.publisher.publish(
                sender="verifier",
                recipient="*",
                kind="agent_failed",
                key="failed",
                payload={"agent_id": "verifier", "role": "verifier", "warning": "Verifier 执行未完成。"},
            )
            raise RuntimeError("boom")

    result = await Orchestrator(
        Config(runs_dir=tmp_path / "runs"),
        pr_loader=fake_loader,
        context_builder=fake_context_builder,
        team_lead=FakeLead([]),
        defect_factory=lambda publisher: SnapshotExpert("defect"),
        intent_factory=lambda publisher: SnapshotExpert("intent"),
        verifier_factory=lambda publisher: PublishingFailure(publisher),
    ).review(ReviewRequest(repo_path=str(tmp_path), base_ref="base", head_ref="head"))

    failed = [
        event
        for event in Orchestrator.read_events(tmp_path / "runs", result.run_id)
        if event.type == "agent.failed" and event.data.get("agent") == "verifier"
    ]
    assert len(failed) == 1


@pytest.mark.asyncio
async def test_budget_warning_precedes_cancellation_and_agent_snapshot_is_recovered(tmp_path: Path) -> None:
    """预算到期前应预警并在有界 grace 内消费专家快照。"""

    finding = make_finding(confidence=0.91)
    warning_seen = asyncio.Event()
    cancelled_after_warning = False

    class SnapshotLead:
        async def plan(self, pr: PRData, packs: list[ContextPack], budget: Budget) -> ReviewPlan:
            return ReviewPlan(
                summary="仅 Defect",
                required_agents=["defect"],
                context_ids=[packs[0].id],
                shards={"defect": [packs[0].id]},
                budget_seconds=budget.seconds,
            )

    class SnapshotOnWarning:
        def __init__(self, publisher) -> None:
            self.publisher = publisher

        async def run(self, context: ContextPack, *, mailbox, **_: object) -> AgentSnapshot:
            nonlocal cancelled_after_warning
            agent_id = f"defect:{context.id}"
            mailbox.register(agent_id)
            try:
                message = await mailbox.receive_one(agent_id, timeout=1)
                assert message.kind == "budget_warning"
                warning_seen.set()
                snapshot = AgentSnapshot(agent_id=agent_id, findings=[finding], pending_checks=["剩余检查"])
                await self.publisher.publish(
                    sender=agent_id,
                    recipient="orchestrator",
                    kind="agent_snapshot",
                    key="snapshot",
                    payload={"snapshot": snapshot.model_dump(mode="json")},
                )
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled_after_warning = warning_seen.is_set()
                raise

    result = await Orchestrator(
        Config(runs_dir=tmp_path / "runs"),
        pr_loader=fake_loader,
        context_builder=fake_context_builder,
        team_lead=SnapshotLead(),
        defect_factory=lambda publisher: SnapshotOnWarning(publisher),
        verifier_factory=lambda publisher: EmptyVerifier(),
        stage_timeouts={"team_review": 0.08},
        budget_grace_seconds=0.04,
    ).review(ReviewRequest(repo_path=str(tmp_path), base_ref="base", head_ref="head"))

    assert result.status == "partial"
    assert warning_seen.is_set()
    assert cancelled_after_warning is True
    assert [item.id for item in result.findings] == [finding.id]


@pytest.mark.asyncio
async def test_planning_and_verifier_receive_their_own_injected_budgets(tmp_path: Path) -> None:
    """Team Lead 与 Verifier 的 Budget 必须来自各自阶段配置。"""

    observed: dict[str, int] = {}

    class BudgetLead(FakeLead):
        async def plan(self, pr: PRData, contexts: list[ContextPack], budget: Budget) -> ReviewPlan:
            observed["planning"] = budget.seconds
            return await super().plan(pr, contexts, budget)

    class BudgetVerifier(EmptyVerifier):
        async def watch(self, mailbox, blackboard, budget: Budget, *, stop_event: asyncio.Event, **kwargs: object) -> list[Verdict]:
            observed["verifier"] = budget.seconds
            return await super().watch(mailbox, blackboard, budget, stop_event=stop_event, **kwargs)

    await Orchestrator(
        Config(runs_dir=tmp_path / "runs"),
        pr_loader=fake_loader,
        context_builder=fake_context_builder,
        team_lead=BudgetLead([]),
        defect_factory=lambda publisher: SnapshotExpert("defect"),
        intent_factory=lambda publisher: SnapshotExpert("intent"),
        verifier_factory=lambda publisher: BudgetVerifier(),
        stage_timeouts={"planning": 7, "verifier": 11},
    ).review(ReviewRequest(repo_path=str(tmp_path), base_ref="base", head_ref="head"))

    assert observed == {"planning": 7, "verifier": 11}


@pytest.mark.asyncio
async def test_reporting_timeout_finishes_all_writes_and_persists_same_partial_result(tmp_path: Path) -> None:
    """报告超时后不得遗留后台线程，返回值与磁盘最终状态必须一致。"""

    active = False

    def slow_persister(result, runs_directory):
        nonlocal active
        active = True
        time.sleep(0.03)
        paths = persist_report(result, runs_directory)
        active = False
        return paths

    result = await Orchestrator(
        Config(runs_dir=tmp_path / "runs"),
        pr_loader=fake_loader,
        context_builder=fake_context_builder,
        team_lead=FakeLead([]),
        defect_factory=lambda publisher: SnapshotExpert("defect"),
        intent_factory=lambda publisher: SnapshotExpert("intent"),
        verifier_factory=lambda publisher: EmptyVerifier(),
        report_persister=slow_persister,
        stage_timeouts={"reporting": 0.01},
    ).review(ReviewRequest(repo_path=str(tmp_path), base_ref="base", head_ref="head"))

    result_path = tmp_path / "runs" / result.run_id / "result.json"
    assert active is False
    assert result.status == "partial"
    assert json.loads(result_path.read_text(encoding="utf-8"))["status"] == "partial"
    before = result_path.read_bytes()
    await asyncio.sleep(0.05)
    assert result_path.read_bytes() == before


@pytest.mark.asyncio
async def test_elapsed_seconds_includes_report_finalization(tmp_path: Path) -> None:
    """最终结果与报告中的总耗时必须覆盖报告生成耗时。"""

    def slow_persister(result, runs_directory):
        time.sleep(0.03)
        return persist_report(result, runs_directory)

    result = await Orchestrator(
        Config(runs_dir=tmp_path / "runs"),
        pr_loader=fake_loader,
        context_builder=fake_context_builder,
        team_lead=FakeLead([]),
        defect_factory=lambda publisher: SnapshotExpert("defect"),
        intent_factory=lambda publisher: SnapshotExpert("intent"),
        verifier_factory=lambda publisher: EmptyVerifier(),
        report_persister=slow_persister,
        stage_timeouts={"reporting": 1},
    ).review(ReviewRequest(repo_path=str(tmp_path), base_ref="base", head_ref="head"))

    persisted = json.loads(
        (tmp_path / "runs" / result.run_id / "result.json").read_text(encoding="utf-8")
    )
    assert result.elapsed_seconds >= 0.03
    assert persisted["elapsed_seconds"] == result.elapsed_seconds


@pytest.mark.asyncio
async def test_entire_run_directory_redacts_sensitive_structured_output_text(tmp_path: Path) -> None:
    """即使 Agent 把敏感内容放入公开字段，整个运行目录也不得落盘。"""

    finding = make_finding().model_copy(
        update={
            "title": "Prompt 泄漏 sensitive-prompt",
            "description": "模型响应 sensitive-response",
            "reasoning_summary": "思维链 sensitive-chain",
        }
    )

    class SensitiveExpert:
        async def run(self, context: ContextPack, **_: object) -> AgentSnapshot:
            return AgentSnapshot(
                agent_id=f"defect:{context.id}",
                findings=[finding],
                warnings=["模型响应包含 sensitive-warning"],
            )

    class AcceptingVerifier:
        async def watch(self, mailbox, blackboard, budget: Budget, *, stop_event: asyncio.Event, **_: object) -> list[Verdict]:
            await stop_event.wait()
            return [
                Verdict(
                    finding_id=finding.id,
                    accepted=True,
                    verdict="confirmed",
                    confidence=0.9,
                    severity="high",
                    reason="已验证。",
                    final_finding=finding,
                )
            ]

    result = await Orchestrator(
        Config(runs_dir=tmp_path / "runs"),
        pr_loader=fake_loader,
        context_builder=fake_context_builder,
        team_lead=FakeLead([]),
        defect_factory=lambda publisher: SensitiveExpert(),
        intent_factory=lambda publisher: SnapshotExpert("intent"),
        verifier_factory=lambda publisher: AcceptingVerifier(),
    ).review(ReviewRequest(repo_path=str(tmp_path), base_ref="base", head_ref="head"))

    run_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "runs" / result.run_id).iterdir()
        if path.is_file()
    )
    for forbidden in (
        "reasoning_summary",
        "Prompt",
        "响应",
        "思维链",
        "sensitive-prompt",
        "sensitive-response",
        "sensitive-chain",
        "sensitive-warning",
    ):
        assert forbidden not in run_text
