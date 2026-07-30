from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Callable
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from reviewcrew.agents.base import AgentRuntime
from reviewcrew.agents.coordinator import ReviewMission, ReviewPlan
from reviewcrew.agents.verifier import filter_and_rank
from reviewcrew.events import EventLogger
from reviewcrew.models import (
    AgentName,
    ContextPack,
    Finding,
    PipelineEvent,
    Verdict,
    WorkflowEdge,
    WorkflowKind,
    WorkflowNode,
    WorkflowNodeStatus,
    WorkflowRelation,
)
from reviewcrew.pipeline.dedupe import dedupe, stable_finding_id
from reviewcrew.tools.toolbox import Toolbox

ExpertName = Literal["defect", "intent"]


class Expert(Protocol):
    async def run(
        self,
        pack: ContextPack,
        toolbox: Toolbox,
        runtime: AgentRuntime,
        task_id: str | None = None,
        objective: str | None = None,
    ) -> list[Finding]: ...


class Verifier(Protocol):
    async def run(
        self,
        findings: list[Finding],
        toolbox: Toolbox,
        timeout_seconds: float = 120,
        task_id: str | None = None,
    ) -> list[Verdict]: ...


class MissionTask(BaseModel):
    id: str
    kind: Literal["review", "cross_check", "verify"]
    agent: Literal["defect", "intent", "verifier"]
    objective: str
    status: WorkflowNodeStatus = "queued"
    priority: int = Field(default=50, ge=1, le=100)
    depends_on: list[str] = Field(default_factory=list)
    context_pack_ids: list[str] = Field(default_factory=list)
    finding_id: str | None = None


class SchedulerSummary(BaseModel):
    findings: list[Finding]
    verdicts: list[Verdict]
    tasks: list[MissionTask]
    max_concurrency: int


def _combine_packs(mission: ReviewMission, packs: dict[str, ContextPack]) -> ContextPack:
    selected = [packs[identifier] for identifier in mission.context_pack_ids if identifier in packs]
    if not selected:
        raise ValueError(f"mission {mission.id} has no available context")
    if len(selected) == 1:
        return selected[0]
    return ContextPack(
        pack_id=mission.id,
        diff_hunks=[diff for pack in selected for diff in pack.diff_hunks],
        enclosing_code={
            key: value
            for pack in selected
            for key, value in pack.enclosing_code.items()
        },
        callers={key: value for pack in selected for key, value in pack.callers.items()},
        callees={key: value for pack in selected for key, value in pack.callees.items()},
        arch_summary="\n".join(pack.arch_summary for pack in selected)[:8192],
        bug_patterns="\n".join(pack.bug_patterns for pack in selected)[:4096],
        intent="\n".join(pack.intent for pack in selected),
        static_signals=[signal for pack in selected for signal in pack.static_signals],
    )


class MissionScheduler:
    def __init__(
        self,
        logger: EventLogger,
        max_concurrency: int = 4,
        max_tasks: int = 24,
        review_timeout: float = 285,
        verify_timeout: float = 105,
        checkpoint_interval: int | None = None,
    ) -> None:
        self.logger = logger
        self.max_concurrency = max_concurrency
        self.max_tasks = max_tasks
        self.review_timeout = review_timeout
        self.verify_timeout = verify_timeout
        self.checkpoint_interval = checkpoint_interval or max(
            1, int(os.getenv("REVIEWCREW_CHECKPOINT_INTERVAL", "10"))
        )
        self._active = 0
        self._max_active = 0

    def _node(
        self,
        identifier: str,
        kind: WorkflowKind,
        label: str,
        status: WorkflowNodeStatus,
        *,
        agent: AgentName | None = None,
        detail: str | None = None,
        task_id: str | None = None,
    ) -> None:
        self.logger.emit(
            PipelineEvent(
                timestamp=time.time(),
                type="workflow_node",
                workflow_node=WorkflowNode(
                    id=identifier,
                    kind=kind,
                    label=label,
                    status=status,
                    agent=agent,
                    detail=detail,
                    task_id=task_id,
                ),
            )
        )

    def _edge(
        self,
        identifier: str,
        source: str,
        target: str,
        relation: WorkflowRelation,
    ) -> None:
        self.logger.emit(
            PipelineEvent(
                timestamp=time.time(),
                type="workflow_edge",
                workflow_edge=WorkflowEdge(
                    id=identifier,
                    source=source,
                    target=target,
                    relation=relation,
                ),
            )
        )

    def _capture_tools(self) -> Callable[[], None]:
        sequence = 0

        def capture(event: PipelineEvent) -> None:
            nonlocal sequence
            if event.type != "tool" or not event.task_id or not event.tool:
                return
            sequence += 1
            tool_id = f"tool-{event.task_id}-{sequence}"
            detail = json.dumps(event.args or {}, ensure_ascii=False)
            self._node(
                tool_id,
                "tool",
                event.tool,
                "completed",
                detail=detail,
                task_id=event.task_id,
            )
            self._edge(f"{event.task_id}-{tool_id}", event.task_id, tool_id, "tool_call")
            self._edge(f"{tool_id}-{event.task_id}", tool_id, event.task_id, "evidence")

        return self.logger.subscribe(capture)

    async def run(
        self,
        plan: ReviewPlan,
        packs: list[ContextPack],
        toolbox: Toolbox,
        experts: dict[ExpertName, Expert],
        verifier: Verifier,
    ) -> SchedulerSummary:
        pack_map = {pack.pack_id: pack for pack in packs}
        self._active = 0
        self._max_active = 0
        missions = {mission.id: mission for mission in plan.missions[: self.max_tasks]}
        tasks = {
            mission.id: MissionTask(
                id=mission.id,
                kind="review",
                agent=mission.agent,
                objective=mission.objective,
                priority=mission.priority,
                depends_on=mission.depends_on,
                context_pack_ids=mission.context_pack_ids,
            )
            for mission in missions.values()
        }
        for mission in missions.values():
            self._node(
                mission.id,
                "agent_task",
                mission.objective,
                "queued",
                agent=mission.agent,
                detail=mission.rationale,
                task_id=mission.id,
            )
            if mission.depends_on:
                for dependency in mission.depends_on:
                    self._edge(
                        f"depends-{dependency}-{mission.id}",
                        dependency,
                        mission.id,
                        "depends_on",
                    )
            else:
                self._edge(f"dispatch-{mission.id}", "coordinator", mission.id, "dispatch")

        semaphore = asyncio.Semaphore(self.max_concurrency)
        records: list[tuple[str, Finding]] = []
        unsubscribe = self._capture_tools()

        async def execute(mission: ReviewMission) -> tuple[str, list[Finding]]:
            task = tasks[mission.id]
            async with semaphore:
                self._active += 1
                self._max_active = max(self._max_active, self._active)
                task.status = "running"
                self._node(
                    task.id,
                    "agent_task",
                    task.objective,
                    "running",
                    agent=task.agent,
                    detail=mission.rationale,
                    task_id=task.id,
                )
                try:
                    findings = await experts[mission.agent].run(
                        _combine_packs(mission, pack_map),
                        toolbox,
                        AgentRuntime(
                            timeout_seconds=self.review_timeout,
                            checkpoint_interval=self.checkpoint_interval,
                        ),
                        task_id=task.id,
                        objective=task.objective,
                    )
                    task.status = "completed"
                    self._node(
                        task.id,
                        "agent_task",
                        task.objective,
                        "completed",
                        agent=task.agent,
                        detail=f"完成，提交 {len(findings)} 条候选 Finding。",
                        task_id=task.id,
                    )
                    return task.id, findings
                except Exception as error:
                    task.status = "failed"
                    self._node(
                        task.id,
                        "agent_task",
                        task.objective,
                        "failed",
                        agent=task.agent,
                        detail=(
                            f"任务失败：{type(error).__name__}: "
                            f"{str(error).replace(chr(10), ' ')[:500]}"
                        ),
                        task_id=task.id,
                    )
                    return task.id, []
                finally:
                    self._active -= 1

        async def verify_one(finding: Finding) -> tuple[MissionTask, list[Verdict]]:
            task_id = f"verify-{finding.id}"
            task = MissionTask(
                id=task_id,
                kind="verify",
                agent="verifier",
                objective=f"质疑候选问题：{finding.title}",
                priority=100,
                finding_id=finding.id,
            )
            tasks[task_id] = task
            self._node(
                task_id,
                "verifier",
                task.objective,
                "queued",
                agent="verifier",
                task_id=task_id,
            )
            self._edge(
                f"challenge-{finding.id}",
                f"finding-{finding.id}",
                task_id,
                "challenge",
            )
            async with semaphore:
                self._active += 1
                self._max_active = max(self._max_active, self._active)
                task.status = "running"
                self._node(
                    task_id,
                    "verifier",
                    task.objective,
                    "running",
                    agent="verifier",
                    task_id=task_id,
                )
                try:
                    verdicts = await verifier.run(
                        [finding], toolbox, self.verify_timeout, task_id=task_id
                    )
                    task.status = "completed"
                    self._node(
                        task_id,
                        "verifier",
                        task.objective,
                        "completed",
                        agent="verifier",
                        detail=verdicts[0].reason if verdicts else "未返回验证结论。",
                        task_id=task_id,
                    )
                    return task, verdicts
                except Exception as error:
                    task.status = "failed"
                    self._node(
                        task_id,
                        "verifier",
                        task.objective,
                        "failed",
                        agent="verifier",
                        detail=f"验证失败：{type(error).__name__}",
                        task_id=task_id,
                    )
                    return task, []
                finally:
                    self._active -= 1

        verifier_jobs: dict[
            str, asyncio.Task[tuple[MissionTask, list[Verdict]]]
        ] = {}
        emitted_candidates: dict[str, Finding] = {}

        def dispatch_verification(source_task_id: str, original: Finding) -> Finding:
            finding = original.model_copy(update={"id": stable_finding_id(original)})
            existing = emitted_candidates.get(finding.id)
            if existing is not None:
                return existing
            emitted_candidates[finding.id] = finding
            finding_node_id = f"finding-{finding.id}"
            self._node(
                finding_node_id,
                "finding",
                finding.title,
                "waiting",
                detail=f"{finding.file}:{finding.line_start}",
            )
            self._edge(
                f"candidate-{source_task_id}-{finding_node_id}",
                source_task_id,
                finding_node_id,
                "candidate",
            )
            self.logger.emit(PipelineEvent(timestamp=time.time(), type="finding", finding=finding))
            verifier_jobs[finding.id] = asyncio.create_task(verify_one(finding))
            return finding

        try:
            running_missions: dict[
                asyncio.Task[tuple[str, list[Finding]]], ReviewMission
            ] = {}
            while True:
                ready = [
                    mission
                    for mission in missions.values()
                    if tasks[mission.id].status == "queued"
                    and all(tasks[item].status == "completed" for item in mission.depends_on)
                ]
                ready.sort(key=lambda item: (-item.priority, item.id))
                for mission in ready:
                    tasks[mission.id].status = "waiting"
                    running_missions[asyncio.create_task(execute(mission))] = mission
                if not running_missions:
                    break

                completed, _ = await asyncio.wait(
                    running_missions, return_when=asyncio.FIRST_COMPLETED
                )
                for job in completed:
                    running_missions.pop(job)
                    task_id, findings = job.result()
                    normalized = [
                        dispatch_verification(task_id, finding) for finding in findings
                    ]
                    records.extend((task_id, finding) for finding in normalized)

                if len(missions) >= self.max_tasks or any(
                    task.kind == "cross_check" for task in tasks.values()
                ):
                    continue
                risky = next(
                    (
                        (task_id, finding)
                        for task_id, finding in records
                        if finding.severity in {"critical", "high"}
                    ),
                    None,
                )
                if risky is None:
                    continue
                source_id, finding = risky
                source_mission = missions[source_id]
                cross_id = f"cross-check-{len(tasks) + 1}"
                cross_agent: ExpertName = (
                    "intent" if source_mission.agent == "defect" else "defect"
                )
                cross = ReviewMission(
                    id=cross_id,
                    agent=cross_agent,
                    objective=f"交叉验证候选问题：{finding.title}",
                    rationale=f"{source_mission.agent} 提交了高风险结论，需要另一视角独立查证。",
                    context_pack_ids=source_mission.context_pack_ids,
                    focus_files=[finding.file],
                    priority=95,
                    depends_on=[source_id],
                )
                missions[cross_id] = cross
                tasks[cross_id] = MissionTask(
                    id=cross_id,
                    kind="cross_check",
                    agent=cross_agent,
                    objective=cross.objective,
                    priority=cross.priority,
                    depends_on=cross.depends_on,
                    context_pack_ids=cross.context_pack_ids,
                )
                self._node(
                    cross_id,
                    "agent_task",
                    cross.objective,
                    "queued",
                    agent=cross_agent,
                    detail=cross.rationale,
                    task_id=cross_id,
                )
                self._edge(f"handoff-{source_id}-{cross_id}", source_id, cross_id, "handoff")

            blocked = [task for task in tasks.values() if task.status == "queued"]
            for task in blocked:
                failed_dependencies = [
                    dependency
                    for dependency in task.depends_on
                    if tasks[dependency].status in {"failed", "cancelled"}
                ]
                task.status = "cancelled"
                detail = (
                    f"依赖任务 {', '.join(failed_dependencies)} 未成功，已取消。"
                    if failed_dependencies
                    else "任务依赖无法满足，已取消。"
                )
                self._node(
                    task.id,
                    "agent_task",
                    task.objective,
                    "cancelled",
                    agent=task.agent,
                    detail=detail,
                    task_id=task.id,
                )
        except BaseException:
            unfinished = [
                job
                for job in [*running_missions, *verifier_jobs.values()]
                if not job.done()
            ]
            for cleanup_job in unfinished:
                cleanup_job.cancel()
            if unfinished:
                await asyncio.gather(*unfinished, return_exceptions=True)
            raise
        finally:
            unsubscribe()

        candidates = dedupe([finding for _, finding in records])
        verified_batches = await asyncio.gather(*verifier_jobs.values())
        verdicts = [verdict for _, batch in verified_batches for verdict in batch]
        by_id = {verdict.finding_id: verdict for verdict in verdicts}
        for finding in candidates:
            verdict = by_id.get(finding.id)
            status: WorkflowNodeStatus = (
                "completed" if verdict and verdict.verdict == "keep" else "cancelled"
            )
            self._node(
                f"finding-{finding.id}",
                "finding",
                finding.title,
                status,
                detail=verdict.reason if verdict else "未通过验证。",
            )
            self._edge(
                f"result-verify-{finding.id}",
                f"verify-{finding.id}",
                f"finding-{finding.id}",
                "result",
            )
        return SchedulerSummary(
            findings=filter_and_rank(candidates, verdicts),
            verdicts=verdicts,
            tasks=list(tasks.values()),
            max_concurrency=self._max_active,
        )
