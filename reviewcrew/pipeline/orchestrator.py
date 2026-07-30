from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel

from reviewcrew.agents.base import AgentRuntime
from reviewcrew.agents.coordinator import CoordinatorAgent, ReviewPlan
from reviewcrew.agents.defect import DefectAgent
from reviewcrew.agents.intent import IntentAgent
from reviewcrew.agents.verifier import VerifierAgent
from reviewcrew.events import EventLogger
from reviewcrew.models import (
    ContextPack,
    FileDiff,
    Finding,
    PipelineEvent,
    Signal,
    Verdict,
    WorkflowEdge,
    WorkflowNode,
)
from reviewcrew.pipeline.context import PRMeta, build_context_packs
from reviewcrew.pipeline.diff_parser import parse_diff
from reviewcrew.pipeline.report import generate_report
from reviewcrew.pipeline.scheduler import MissionScheduler
from reviewcrew.profile.builder import RepoProfile, build_profile
from reviewcrew.profile.indexer import RepoIndex
from reviewcrew.signals import DepsProvider, LinterProvider, SemgrepProvider, SignalProvider
from reviewcrew.tools.toolbox import Toolbox

DiffLoader = Callable[[str], Awaitable[str]]
MetaLoader = Callable[[str], Awaitable[PRMeta]]
StageResult = TypeVar("StageResult")


class Expert(Protocol):
    async def run(
        self,
        pack: ContextPack,
        toolbox: Toolbox,
        runtime: AgentRuntime,
        task_id: str | None = None,
        objective: str | None = None,
    ) -> list[Finding]: ...


class Coordinator(Protocol):
    async def run(self, packs: list[ContextPack], timeout_seconds: float = 45) -> ReviewPlan: ...


class Verifier(Protocol):
    async def run(
        self,
        findings: list[Finding],
        toolbox: Toolbox,
        timeout_seconds: float = 120,
        task_id: str | None = None,
    ) -> list[Verdict]: ...


class ReviewResult(BaseModel):
    run_id: str
    findings: list[Finding]
    elapsed_seconds: float
    stages: dict[str, float]


async def fetch_diff(pr_url: str) -> str:
    local = Path(pr_url)
    if local.is_file():
        return local.read_text(encoding="utf-8")
    url = pr_url if pr_url.endswith(".diff") else f"{pr_url.rstrip('/')}.diff"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def fetch_meta(pr_url: str) -> PRMeta:
    return PRMeta(title=f"Review {pr_url}")


class Orchestrator:
    def __init__(
        self,
        *,
        runs_dir: Path = Path("runs"),
        diff_loader: DiffLoader = fetch_diff,
        meta_loader: MetaLoader = fetch_meta,
        signal_providers: list[SignalProvider] | None = None,
        defect_agent: Expert | None = None,
        intent_agent: Expert | None = None,
        verifier: Verifier | None = None,
        coordinator: Coordinator | None = None,
        max_concurrent_agents: int | None = None,
        pipeline_timeout_seconds: float | None = None,
    ) -> None:
        self.runs_dir = runs_dir
        self.diff_loader = diff_loader
        self.meta_loader = meta_loader
        self.signal_providers = signal_providers or [
            SemgrepProvider(),
            LinterProvider(),
            DepsProvider(),
        ]
        self.defect_agent = defect_agent
        self.intent_agent = intent_agent
        self.verifier = verifier
        self.coordinator = coordinator
        self.max_concurrent_agents = max_concurrent_agents or int(
            os.getenv("REVIEWCREW_MAX_AGENTS", "4")
        )
        self.pipeline_timeout_seconds = pipeline_timeout_seconds or int(
            os.getenv("REVIEWCREW_TIMEOUT", "600")
        )

    async def _stage(
        self,
        logger: EventLogger,
        stages: dict[str, float],
        name: str,
        operation: Callable[[], Awaitable[StageResult]],
        timeout: float,
    ) -> StageResult:
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(operation(), timeout=timeout)
        except Exception:
            elapsed = time.monotonic() - started
            stages[name] = elapsed
            raise
        elapsed = time.monotonic() - started
        stages[name] = elapsed
        return result

    async def review(self, pr_url: str, repo_path: Path, run_id: str | None = None) -> ReviewResult:
        return await asyncio.wait_for(
            self._review(pr_url, repo_path, run_id),
            timeout=self.pipeline_timeout_seconds,
        )

    async def _review(
        self, pr_url: str, repo_path: Path, run_id: str | None = None
    ) -> ReviewResult:
        started = time.monotonic()
        run_id = run_id or f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        logger = EventLogger(run_id, self.runs_dir)
        stages: dict[str, float] = {}
        logger.emit(
            PipelineEvent(
                timestamp=time.time(),
                type="workflow_node",
                workflow_node=WorkflowNode(
                    id="input",
                    kind="input",
                    label="审查输入",
                    status="running",
                    detail="正在解析 diff 并构建仓库上下文。",
                ),
            )
        )

        async def preprocess() -> tuple[list[FileDiff], PRMeta]:
            raw_diff, meta = await asyncio.gather(
                self.diff_loader(pr_url), self.meta_loader(pr_url)
            )
            logger.run_dir.joinpath("change.diff").write_text(raw_diff, encoding="utf-8")
            return list(parse_diff(raw_diff)), meta

        diffs, meta = await self._stage(logger, stages, "preprocess", preprocess, 10)
        if not diffs:
            raise ValueError("pull request diff contains no reviewable source changes")
        logger.emit(
            PipelineEvent(
                timestamp=time.time(),
                type="workflow_node",
                workflow_node=WorkflowNode(
                    id="input",
                    kind="input",
                    label="审查输入",
                    status="running",
                    detail=f"已解析 {len(diffs)} 个变更文件，正在构建增量仓库上下文。",
                ),
            )
        )

        async def context() -> tuple[list[ContextPack], RepoIndex, RepoProfile]:
            files = [diff.path for diff in diffs]
            profile = await asyncio.to_thread(build_profile, repo_path, files)
            index = RepoIndex(profile.index_path, repo_path)
            scans = await asyncio.gather(
                *(provider.scan(repo_path, files) for provider in self.signal_providers),
                return_exceptions=True,
            )
            signals: list[Signal] = []
            for scan in scans:
                if isinstance(scan, list):
                    signals.extend(scan)
            packs = build_context_packs(diffs, index, profile, signals, meta)
            return packs, index, profile

        packs, index, _profile = await self._stage(logger, stages, "context", context, 180)
        toolbox = Toolbox(repo_path, index)
        defect = self.defect_agent or DefectAgent(event_logger=logger)
        intent = self.intent_agent or IntentAgent(event_logger=logger)
        logger.emit(
            PipelineEvent(
                timestamp=time.time(),
                type="workflow_node",
                workflow_node=WorkflowNode(
                    id="input",
                    kind="input",
                    label="审查输入",
                    status="completed",
                    detail=f"已生成 {len(packs)} 个上下文包。",
                ),
            )
        )
        logger.emit(
            PipelineEvent(
                timestamp=time.time(),
                type="workflow_node",
                workflow_node=WorkflowNode(
                    id="coordinator",
                    kind="coordinator",
                    label="Coordinator 调度规划",
                    status="running",
                    agent="coordinator",
                    task_id="coordinator",
                ),
            )
        )
        logger.emit(
            PipelineEvent(
                timestamp=time.time(),
                type="workflow_edge",
                workflow_edge=WorkflowEdge(
                    id="input-coordinator",
                    source="input",
                    target="coordinator",
                    relation="dispatch",
                ),
            )
        )
        coordinator = self.coordinator or CoordinatorAgent()
        plan_started = time.monotonic()
        plan = await coordinator.run(packs, 45)
        stages["coordinate"] = time.monotonic() - plan_started
        logger.emit(
            PipelineEvent(
                timestamp=time.time(),
                type="thought",
                agent="coordinator",
                task_id="coordinator",
                text=plan.summary,
            )
        )
        logger.emit(
            PipelineEvent(
                timestamp=time.time(),
                type="workflow_node",
                workflow_node=WorkflowNode(
                    id="coordinator",
                    kind="coordinator",
                    label="Coordinator 调度规划",
                    status="completed",
                    agent="coordinator",
                    detail=f"已派发 {len(plan.missions)} 个审查任务。",
                    task_id="coordinator",
                ),
            )
        )
        verifier = self.verifier or VerifierAgent(event_logger=logger)
        schedule_started = time.monotonic()
        scheduler = MissionScheduler(logger, max_concurrency=self.max_concurrent_agents)
        summary = await scheduler.run(
            plan,
            packs,
            toolbox,
            {"defect": defect, "intent": intent},
            verifier,
        )
        stages["schedule"] = time.monotonic() - schedule_started
        reviewed = summary.findings

        async def report() -> tuple[str, dict[str, list[dict[str, object]]]]:
            logger.emit(
                PipelineEvent(
                    timestamp=time.time(),
                    type="workflow_node",
                    workflow_node=WorkflowNode(
                        id="report",
                        kind="report",
                        label="汇总审查报告",
                        status="running",
                    ),
                )
            )
            for finding in reviewed:
                logger.emit(
                    PipelineEvent(
                        timestamp=time.time(),
                        type="workflow_edge",
                        workflow_edge=WorkflowEdge(
                            id=f"report-{finding.id}",
                            source=f"finding-{finding.id}",
                            target="report",
                            relation="result",
                        ),
                    )
                )
            markdown, comments = generate_report(reviewed)
            logger.run_dir.joinpath("report.md").write_text(markdown, encoding="utf-8")
            logger.run_dir.joinpath("github_comments.json").write_text(
                json.dumps(comments, indent=2), encoding="utf-8"
            )
            logger.emit(PipelineEvent(timestamp=time.time(), type="report", markdown=markdown))
            logger.emit(
                PipelineEvent(
                    timestamp=time.time(),
                    type="workflow_node",
                    workflow_node=WorkflowNode(
                        id="report",
                        kind="report",
                        label="汇总审查报告",
                        status="completed",
                        detail=f"已汇总 {len(reviewed)} 条候选 Finding。",
                    ),
                )
            )
            return markdown, comments

        await self._stage(logger, stages, "report", report, 20)
        return ReviewResult(
            run_id=run_id,
            findings=reviewed,
            elapsed_seconds=time.monotonic() - started,
            stages=stages,
        )
