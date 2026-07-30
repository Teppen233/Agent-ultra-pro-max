from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Literal

from reviewcrew.agents.base import AgentRuntime
from reviewcrew.agents.coordinator import ReviewMission, ReviewPlan
from reviewcrew.events import EventLogger
from reviewcrew.models import (
    Category,
    ContextPack,
    FileDiff,
    Finding,
    PipelineEvent,
    Severity,
    Verdict,
)
from reviewcrew.pipeline.scheduler import MissionScheduler
from reviewcrew.profile.indexer import RepoIndex
from reviewcrew.tools.toolbox import Toolbox


def make_pack() -> ContextPack:
    return ContextPack(
        pack_id="auth",
        diff_hunks=[FileDiff(path="app.py", change_type="modify", hunks=[])],
    )


def make_finding(
    title: str,
    severity: Severity = "medium",
    line: int = 1,
    category: Category = "security",
) -> Finding:
    return Finding(
        category=category,
        severity=severity,
        confidence=0.88,
        file="app.py",
        line_start=line,
        line_end=line,
        title=title,
        reasoning="外部输入可达敏感操作。",
        trigger_path="request -> operation",
        suggestion="在边界处校验输入。",
    )


class RecordingExpert:
    def __init__(
        self,
        name: Literal["defect", "intent"],
        events: list[str],
        finding: Finding | None = None,
        delay: float = 0.01,
        fail_task: str | None = None,
        logger: EventLogger | None = None,
    ) -> None:
        self.name = name
        self.events = events
        self.finding = finding
        self.delay = delay
        self.fail_task = fail_task
        self.logger = logger

    async def run(
        self,
        pack: ContextPack,
        toolbox: Toolbox,
        runtime: AgentRuntime,
        task_id: str | None = None,
        objective: str | None = None,
    ) -> list[Finding]:
        del pack, toolbox, runtime, objective
        identifier = task_id or self.name
        self.events.append(f"start:{identifier}")
        if self.logger is not None:
            self.logger.emit(
                PipelineEvent(
                    timestamp=time.time(),
                    type="tool",
                    agent=self.name,
                    task_id=identifier,
                    tool="read_file",
                    args={"path": "app.py"},
                )
            )
        await asyncio.sleep(self.delay)
        if identifier == self.fail_task:
            raise RuntimeError("expected failure")
        self.events.append(f"done:{identifier}")
        if self.finding is not None and not identifier.startswith("cross"):
            return [self.finding]
        return []


class RecordingVerifier:
    def __init__(self) -> None:
        self.task_ids: list[str] = []

    async def run(
        self,
        findings: list[Finding],
        toolbox: Toolbox,
        timeout_seconds: float = 120,
        task_id: str | None = None,
    ) -> list[Verdict]:
        del toolbox, timeout_seconds
        if task_id is not None:
            self.task_ids.append(task_id)
        await asyncio.sleep(0.01)
        return [
            Verdict(
                finding_id=finding.id,
                verdict="keep",
                reason="证据链完整。",
                confidence_adjusted=0.9,
            )
            for finding in findings
        ]


def make_toolbox(tmp_path: Path) -> Toolbox:
    (tmp_path / "app.py").write_text("value = input()\n", encoding="utf-8")
    return Toolbox(tmp_path, RepoIndex.build(tmp_path, ["python"]))


async def test_scheduler_runs_ready_tasks_concurrently_and_fans_out_verifiers(
    tmp_path: Path,
) -> None:
    logger = EventLogger("scheduler", tmp_path / "runs")
    captured: list[PipelineEvent] = []
    logger.subscribe(captured.append)
    activity: list[str] = []
    plan = ReviewPlan(
        summary="并行检查",
        missions=[
            ReviewMission(
                id="security",
                agent="defect",
                objective="检查认证边界",
                rationale="外部输入发生变化",
                context_pack_ids=["auth"],
                priority=90,
            ),
            ReviewMission(
                id="intent",
                agent="intent",
                objective="核对业务意图",
                rationale="权限语义发生变化",
                context_pack_ids=["auth"],
                priority=80,
            ),
        ],
    )
    verifier = RecordingVerifier()
    summary = await MissionScheduler(logger, max_concurrency=2).run(
        plan,
        [make_pack()],
        make_toolbox(tmp_path),
        {
            "defect": RecordingExpert(
                "defect", activity, make_finding("认证绕过", line=3), logger=logger
            ),
            "intent": RecordingExpert(
                "intent",
                activity,
                make_finding("权限语义错误", line=20, category="logic"),
                logger=logger,
            ),
        },
        verifier,
    )

    assert activity[:2] == ["start:security", "start:intent"]
    assert summary.max_concurrency == 2
    assert len(verifier.task_ids) == 2
    assert all(task.status == "completed" for task in summary.tasks)
    nodes = [event.workflow_node for event in captured if event.workflow_node is not None]
    edges = [event.workflow_edge for event in captured if event.workflow_edge is not None]
    assert any(node.kind == "tool" for node in nodes)
    assert sum(node.kind == "verifier" and node.status == "queued" for node in nodes) == 2
    assert {edge.relation for edge in edges} >= {
        "dispatch",
        "tool_call",
        "evidence",
        "candidate",
        "challenge",
        "result",
    }


async def test_scheduler_adds_one_cross_check_and_cancels_blocked_task(tmp_path: Path) -> None:
    logger = EventLogger("cross-check", tmp_path / "runs")
    captured: list[PipelineEvent] = []
    logger.subscribe(captured.append)
    activity: list[str] = []
    plan = ReviewPlan(
        summary="风险检查",
        missions=[
            ReviewMission(
                id="primary",
                agent="defect",
                objective="检查高风险改动",
                rationale="触达敏感路径",
                context_pack_ids=["auth"],
                priority=100,
            ),
            ReviewMission(
                id="broken",
                agent="intent",
                objective="模拟失败任务",
                rationale="验证失败传播",
                context_pack_ids=["auth"],
                priority=90,
            ),
            ReviewMission(
                id="dependent",
                agent="defect",
                objective="依赖失败任务",
                rationale="验证取消状态",
                context_pack_ids=["auth"],
                depends_on=["broken"],
            ),
        ],
    )
    summary = await MissionScheduler(logger, max_concurrency=3).run(
        plan,
        [make_pack()],
        make_toolbox(tmp_path),
        {
            "defect": RecordingExpert(
                "defect", activity, make_finding("凭据泄露", "high", 7)
            ),
            "intent": RecordingExpert("intent", activity, fail_task="broken"),
        },
        RecordingVerifier(),
    )

    by_id = {task.id: task for task in summary.tasks}
    assert by_id["broken"].status == "failed"
    assert by_id["dependent"].status == "cancelled"
    cross_checks = [task for task in summary.tasks if task.kind == "cross_check"]
    assert len(cross_checks) == 1
    assert cross_checks[0].agent == "intent"
    edges = [event.workflow_edge for event in captured if event.workflow_edge is not None]
    assert sum(edge.relation == "handoff" for edge in edges) == 1


async def test_scheduler_starts_verification_before_slowest_expert_finishes(
    tmp_path: Path,
) -> None:
    activity: list[str] = []

    class TimelineVerifier(RecordingVerifier):
        async def run(
            self,
            findings: list[Finding],
            toolbox: Toolbox,
            timeout_seconds: float = 120,
            task_id: str | None = None,
        ) -> list[Verdict]:
            activity.append("verify:start")
            return await super().run(findings, toolbox, timeout_seconds, task_id)

    plan = ReviewPlan(
        summary="完成即验证",
        missions=[
            ReviewMission(
                id="fast",
                agent="defect",
                objective="快速检查",
                rationale="尽早产生候选",
                context_pack_ids=["auth"],
                priority=100,
            ),
            ReviewMission(
                id="slow",
                agent="intent",
                objective="深度检查",
                rationale="模拟长任务",
                context_pack_ids=["auth"],
                priority=90,
            ),
        ],
    )
    summary = await MissionScheduler(
        EventLogger("streaming", tmp_path / "runs"), max_concurrency=2
    ).run(
        plan,
        [make_pack()],
        make_toolbox(tmp_path),
        {
            "defect": RecordingExpert(
                "defect", activity, make_finding("快速候选"), delay=0.01
            ),
            "intent": RecordingExpert("intent", activity, delay=0.12),
        },
        TimelineVerifier(),
    )

    assert activity.index("verify:start") < activity.index("done:slow")
    assert summary.max_concurrency == 2
