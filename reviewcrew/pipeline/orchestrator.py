"""确定性编排 PR 加载、上下文、Agent Team、验证和报告持久化。"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from reviewcrew.agents.defect import DefectAgent
from reviewcrew.agents.intent import IntentAgent
from reviewcrew.agents.team_lead import TeamLeadAgent
from reviewcrew.agents.verifier import VerifierAgent
from reviewcrew.config import Config
from reviewcrew.context.builder import build_context
from reviewcrew.events import EventStore, PipelineEvent
from reviewcrew.github.pr_loader import PRLoadError, load_pr
from reviewcrew.pipeline.dedupe import deduplicate_findings
from reviewcrew.report import persist_report
from reviewcrew.schemas import (
    AgentSnapshot,
    Budget,
    ContextPack,
    Finding,
    PRData,
    ReviewPlan,
    ReviewRequest,
    ReviewResult,
    StaticSignal,
    Verdict,
)
from reviewcrew.team.blackboard import EvidenceBlackboard
from reviewcrew.team.mailbox import Mailbox
from reviewcrew.team.publisher import MessagePublisher


PRLoader = Callable[[ReviewRequest, Config], Awaitable[PRData]]
ContextBuilder = Callable[..., Awaitable[list[ContextPack]]]
StaticAnalyzer = Callable[[PRData, list[ContextPack]], Awaitable[list[StaticSignal]]]
AgentFactory = Callable[[MessagePublisher], object]
ReportPersister = Callable[[ReviewResult, str | Path], tuple[Path, Path]]


class TeamLeadProtocol(Protocol):
    """Team Lead 的最小可注入协议。"""

    async def plan(self, pr: PRData, contexts: list[ContextPack], budget: Budget) -> ReviewPlan:
        """返回结构化审查计划。"""


class StageTimeoutError(TimeoutError):
    """表示一个具有明确名称的流水线阶段超时。"""

    def __init__(self, stage: str) -> None:
        super().__init__(stage)
        self.stage = stage


@dataclass(slots=True)
class _RunState:
    """保存可在取消和超时后继续汇总的公开运行状态。"""

    run_id: str
    started_at: datetime
    mailbox: Mailbox
    blackboard: EvidenceBlackboard
    publisher: MessagePublisher
    pr: PRData | None = None
    contexts: list[ContextPack] = field(default_factory=list)
    plan: ReviewPlan | None = None
    snapshots: dict[str, AgentSnapshot] = field(default_factory=dict)
    verdicts: list[Verdict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False
    failed: bool = False
    verifier_failed: bool = False
    global_timed_out: bool = False
    active_stage: str | None = None
    terminal_stages: set[str] = field(default_factory=set)


class _EventingPublisher(MessagePublisher):
    """在统一消息发布成功后同步生成脱敏 PipelineEvent。"""

    def __init__(self, *, mailbox: Mailbox, blackboard: EvidenceBlackboard, events: EventStore) -> None:
        super().__init__(mailbox=mailbox, blackboard=blackboard)
        self._events = events

    async def publish(self, **arguments: Any) -> bool:
        """发布团队消息，并仅映射公开摘要到事件流。"""

        published = await super().publish(**arguments)
        if not published:
            return False
        kind = arguments["kind"]
        payload = arguments.get("payload", {})
        sender = arguments["sender"]
        if kind == "candidate_finding":
            finding = payload.get("finding", {})
            self._events.emit(
                self.run_id,
                "agent.candidate",
                {
                    "agent": sender,
                    "finding_id": finding.get("id"),
                    "file": finding.get("file"),
                    "line": finding.get("line_start"),
                    "severity": finding.get("severity"),
                },
            )
        elif kind in {"agent_completed", "agent_failed"}:
            event_type = "agent.completed" if kind == "agent_completed" else "agent.failed"
            self._events.emit(
                self.run_id,
                event_type,
                {
                    "agent": payload.get("agent_id", sender),
                    "role": payload.get("role"),
                    "warning": payload.get("warning"),
                },
            )
        elif kind == "verdict":
            verdict = payload.get("verdict", {})
            event_type = "verifier.accepted" if verdict.get("accepted") else "verifier.rejected"
            self._events.emit(
                self.run_id,
                event_type,
                {
                    "finding_id": verdict.get("finding_id"),
                    "verdict": verdict.get("verdict"),
                    "confidence": verdict.get("confidence"),
                },
            )
        return True


class Orchestrator:
    """使用普通 asyncio 代码驱动一次可降级、可审计的审查运行。"""

    _STAGE_LABELS = {
        "loading_pr": "PR 加载",
        "building_context": "上下文构建",
        "planning": "审查规划",
        "team_review": "Agent Team 审查",
        "reporting": "报告生成",
    }

    def __init__(
        self,
        config: Config | None = None,
        *,
        pr_loader: PRLoader = load_pr,
        context_builder: ContextBuilder | None = None,
        team_lead: TeamLeadProtocol | None = None,
        defect_factory: AgentFactory | None = None,
        intent_factory: AgentFactory | None = None,
        verifier_factory: AgentFactory | None = None,
        static_analyzer: StaticAnalyzer | None = None,
        event_store: EventStore | None = None,
        report_persister: ReportPersister = persist_report,
        stage_timeouts: Mapping[str, float] | None = None,
        global_timeout_seconds: float | None = None,
    ) -> None:
        self.config = config or Config()
        self._pr_loader = pr_loader
        self._context_builder = context_builder or self._default_context_builder
        self._team_lead = team_lead or TeamLeadAgent(config=self.config)
        self._defect_factory = defect_factory or (
            lambda publisher: DefectAgent(config=self.config, publisher=publisher)
        )
        self._intent_factory = intent_factory or (
            lambda publisher: IntentAgent(config=self.config, publisher=publisher)
        )
        self._verifier_factory = verifier_factory or (
            lambda publisher: VerifierAgent(config=self.config, publisher=publisher)
        )
        self._static_analyzer = static_analyzer
        self._events = event_store or EventStore(self.config.runs_dir)
        self._persist_report = report_persister
        self._global_timeout = global_timeout_seconds or float(self.config.global_timeout_seconds)
        self._timeouts = {
            "loading_pr": float(self.config.pr_load_timeout_seconds),
            "building_context": float(self.config.context_timeout_seconds),
            "planning": float(self.config.review_timeout_seconds),
            "team_review": float(self.config.review_timeout_seconds),
            "reporting": float(self.config.report_timeout_seconds),
            **dict(stage_timeouts or {}),
        }

    async def review(self, request: ReviewRequest) -> ReviewResult:
        """执行一次审查，并在任何超时路径上返回已持久化的 ReviewResult。"""

        run_id = self._events.create_run()
        started_at = datetime.now(UTC)
        mailbox = Mailbox(self.config.runs_dir, run_id)
        blackboard = EvidenceBlackboard(run_id)
        publisher = _EventingPublisher(mailbox=mailbox, blackboard=blackboard, events=self._events)
        state = _RunState(run_id, started_at, mailbox, blackboard, publisher)
        self._events.emit(run_id, "review.started", {"mode": self._request_mode(request)})

        try:
            async with asyncio.timeout(self._global_timeout):
                await self._run_core(request, state)
        except StageTimeoutError as error:
            state.degraded = True
            label = self._STAGE_LABELS[error.stage]
            state.warnings.append(f"{label}阶段超时，已保存当前可用结果。")
        except TimeoutError:
            state.degraded = True
            state.verifier_failed = True
            state.global_timed_out = True
            state.warnings.append("全局审查超时，已终止未完成任务并保存当前可用结果。")
            self._fail_active_stage(state, "全局 watchdog 超时")
        except Exception as error:
            state.failed = True
            state.warnings.append(self._safe_failure_message(error))

        result = self._build_result(state)
        try:
            await self._run_stage(
                state,
                "reporting",
                lambda: asyncio.to_thread(self._persist_report, result, self.config.runs_dir),
            )
        except StageTimeoutError:
            state.degraded = True
            state.warnings.append("报告生成阶段超时，结果文件可能不完整。")
            result = self._build_result(state)
        except Exception as error:
            state.degraded = True
            state.warnings.append(f"报告生成失败：{type(error).__name__}。")
            result = self._build_result(state)
        else:
            self._events.emit(run_id, "report.generated", {"status": result.status})

        final_type = "review.failed" if result.status == "failed" else "review.completed"
        self._events.emit(run_id, final_type, {"status": result.status})
        return result

    async def _run_core(self, request: ReviewRequest, state: _RunState) -> None:
        state.pr = await self._run_stage(
            state,
            "loading_pr",
            lambda: self._pr_loader(request, self.config),
        )
        state.contexts = await self._run_stage(
            state,
            "building_context",
            lambda: self._call_context_builder(state.pr, request),
        )
        for context in state.contexts:
            await state.publisher.publish(
                sender="orchestrator",
                recipient="*",
                kind="context_available",
                key=f"context:{context.id}",
                payload={"context_id": context.id, "files": context.files},
            )
        planning_budget = Budget(seconds=max(1, int(self._timeouts["team_review"])))
        state.plan = await self._run_stage(
            state,
            "planning",
            lambda: self._team_lead.plan(state.pr, state.contexts, planning_budget),
        )
        await state.publisher.publish(
            sender="team_lead",
            recipient="*",
            kind="review_plan",
            key="review-plan",
            payload=state.plan.model_dump(mode="json"),
        )
        await self._run_stage(state, "team_review", lambda: self._run_team(state))

    async def _run_team(self, state: _RunState) -> None:
        if state.pr is None or state.plan is None:
            return
        contexts = state.contexts or [self._empty_context(state.pr)]
        expected_agent_ids = {
            f"{role}:{context.id}" for role in ("defect", "intent") for context in contexts
        }
        stop_event = asyncio.Event()
        watcher_task: asyncio.Task[list[Verdict] | None] | None = None
        expert_tasks: list[asyncio.Task[AgentSnapshot | None]] = []
        static_task: asyncio.Task[None] | None = None
        try:
            async with asyncio.TaskGroup() as group:
                watcher_task = group.create_task(
                    self._run_verifier(state, expected_agent_ids, stop_event),
                    name="reviewcrew-verifier",
                )
                for role, factory in (
                    ("defect", self._defect_factory),
                    ("intent", self._intent_factory),
                ):
                    for context in contexts:
                        expert_tasks.append(
                            group.create_task(
                                self._run_expert(state, role, factory, context),
                                name=f"reviewcrew-{role}-{context.id}",
                            )
                        )
                if self._static_analyzer is not None:
                    static_task = group.create_task(
                        self._run_static_analyzer(state),
                        name="reviewcrew-static",
                    )
                group.create_task(
                    self._stop_watcher_after_experts(expert_tasks, stop_event),
                    name="reviewcrew-watcher-stop",
                )
        finally:
            stop_event.set()
            if watcher_task is not None and not watcher_task.done():
                watcher_task.cancel()
            if static_task is not None and not static_task.done():
                static_task.cancel()

    async def _run_expert(
        self,
        state: _RunState,
        role: str,
        factory: AgentFactory,
        context: ContextPack,
    ) -> AgentSnapshot | None:
        agent_id = f"{role}:{context.id}"
        self._events.emit(state.run_id, "agent.started", {"agent": agent_id, "role": role})
        agent = factory(state.publisher)
        budget = Budget(seconds=max(1, int(self._timeouts["team_review"])))
        try:
            snapshot = await self._call_with_supported_keywords(
                agent.run,
                context,
                mailbox=state.mailbox,
                blackboard=state.blackboard,
                plan=state.plan,
                budget=budget,
            )
            if not isinstance(snapshot, AgentSnapshot):
                snapshot = AgentSnapshot.model_validate(snapshot)
            state.snapshots[agent_id] = snapshot
            state.warnings.extend(snapshot.warnings)
            await self._publish_terminal_if_missing(state, agent_id, role, failed=False)
            return snapshot
        except asyncio.CancelledError:
            await asyncio.shield(self._publish_budget_warning(state, agent_id, role))
            raise
        except Exception:
            state.degraded = True
            label = "Defect" if role == "defect" else "Intent"
            state.warnings.append(f"{label} 专家执行失败，已继续使用其他可用结果。")
            await self._publish_terminal_if_missing(state, agent_id, role, failed=True)
            return None

    async def _run_verifier(
        self,
        state: _RunState,
        expected_agent_ids: set[str],
        stop_event: asyncio.Event,
    ) -> list[Verdict] | None:
        self._events.emit(state.run_id, "verifier.started", {"agent": "verifier"})
        verifier = self._verifier_factory(state.publisher)
        budget = Budget(seconds=max(1, int(self.config.verifier_timeout_seconds)))
        try:
            verdicts = await self._call_with_supported_keywords(
                verifier.watch,
                state.mailbox,
                state.blackboard,
                budget,
                expected_agent_ids=expected_agent_ids,
                stop_event=stop_event,
            )
            state.verdicts = [
                item if isinstance(item, Verdict) else Verdict.model_validate(item) for item in verdicts
            ]
            published_finding_ids = {
                message.payload.get("verdict", {}).get("finding_id")
                for message in state.blackboard.by_kind("verdict")
            }
            for verdict in state.verdicts:
                if verdict.finding_id in published_finding_ids:
                    continue
                self._events.emit(
                    state.run_id,
                    "verifier.accepted" if verdict.accepted else "verifier.rejected",
                    {
                        "finding_id": verdict.finding_id,
                        "verdict": verdict.verdict,
                        "confidence": verdict.confidence,
                    },
                )
            self._events.emit(
                state.run_id,
                "verifier.completed",
                {"accepted": sum(item.accepted for item in state.verdicts)},
            )
            return state.verdicts
        except asyncio.CancelledError:
            raise
        except Exception:
            state.degraded = True
            state.verifier_failed = True
            state.warnings.append("Verifier 执行失败，仅保留高置信候选，且这些候选未经完整验证。")
            self._events.emit(state.run_id, "agent.failed", {"agent": "verifier", "role": "verifier"})
            return None

    async def _run_static_analyzer(self, state: _RunState) -> None:
        if self._static_analyzer is None or state.pr is None:
            return
        try:
            signals = await self._static_analyzer(state.pr, state.contexts)
        except asyncio.CancelledError:
            raise
        except Exception:
            state.degraded = True
            state.warnings.append("静态分析工具执行失败，已使用其他证据继续审查。")
            return
        for signal in signals:
            await state.publisher.publish(
                sender="static",
                recipient="*",
                kind="static_signal",
                key=f"signal:{signal.provider}:{signal.rule_id}:{signal.file}:{signal.line}",
                payload=signal.model_dump(mode="json"),
            )

    async def _stop_watcher_after_experts(
        self,
        expert_tasks: list[asyncio.Task[AgentSnapshot | None]],
        stop_event: asyncio.Event,
    ) -> None:
        await asyncio.gather(*expert_tasks, return_exceptions=True)
        stop_event.set()

    async def _publish_terminal_if_missing(
        self,
        state: _RunState,
        agent_id: str,
        role: str,
        *,
        failed: bool,
    ) -> None:
        for message in state.blackboard.messages:
            if message.kind in {"agent_completed", "agent_failed"} and message.payload.get("agent_id") == agent_id:
                return
        await state.publisher.publish(
            sender=agent_id,
            recipient="*",
            kind="agent_failed" if failed else "agent_completed",
            key="failed" if failed else "completed",
            payload={
                "agent_id": agent_id,
                "role": role,
                **({"warning": "专家执行未完成。"} if failed else {}),
            },
        )

    async def _publish_budget_warning(self, state: _RunState, agent_id: str, role: str) -> None:
        await state.publisher.publish(
            sender="orchestrator",
            recipient=agent_id,
            kind="budget_warning",
            key=f"budget:{agent_id}",
            payload={"agent_id": agent_id, "role": role, "request_snapshot": True},
        )

    async def _run_stage(
        self,
        state: _RunState,
        stage: str,
        operation: Callable[[], Awaitable[Any]],
    ) -> Any:
        self._events.emit(state.run_id, "stage.started", {"stage": stage})
        state.active_stage = stage
        try:
            async with asyncio.timeout(self._timeouts[stage]):
                result = await operation()
        except TimeoutError as error:
            self._events.emit(
                state.run_id,
                "stage.failed",
                {"stage": stage, "reason": "timeout"},
            )
            state.terminal_stages.add(stage)
            state.active_stage = None
            raise StageTimeoutError(stage) from error
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._events.emit(
                state.run_id,
                "stage.failed",
                {"stage": stage, "reason": type(error).__name__},
            )
            state.terminal_stages.add(stage)
            state.active_stage = None
            raise
        self._events.emit(state.run_id, "stage.completed", {"stage": stage})
        state.terminal_stages.add(stage)
        state.active_stage = None
        return result

    async def _call_context_builder(
        self,
        pr: PRData,
        request: ReviewRequest,
    ) -> list[ContextPack]:
        return await self._call_with_supported_keywords(
            self._context_builder,
            pr,
            request,
            self.config,
            request=request,
            config=self.config,
        )

    async def _default_context_builder(
        self,
        pr: PRData,
        request: ReviewRequest,
        config: Config,
    ) -> list[ContextPack]:
        if request.repo_path is not None:
            return await build_context(pr, Path(request.repo_path).resolve(), config)
        return [
            ContextPack(
                id=f"ctx-{index}",
                repository=pr.repository,
                base_sha=pr.base_sha,
                head_sha=pr.head_sha,
                pr_title=pr.title,
                pr_description=pr.description,
                files=[changed_file.path],
                diff_hunks=changed_file.hunks,
                retrieval_notes=["GitHub 模式仅使用 PR 差异构建基础上下文。"],
            )
            for index, changed_file in enumerate(pr.files, start=1)
        ]

    @staticmethod
    async def _call_with_supported_keywords(callable_object: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        """只向显式声明的注入接口传递可选协作参数。"""

        signature = inspect.signature(callable_object)
        parameters = signature.parameters
        accepts_keywords = any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values())
        accepted = kwargs if accepts_keywords else {key: value for key, value in kwargs.items() if key in parameters}
        positional_names = [
            name
            for name, parameter in parameters.items()
            if parameter.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
        ]
        occupied = set(positional_names[: len(args)])
        accepted = {key: value for key, value in accepted.items() if key not in occupied}
        return await callable_object(*args, **accepted)

    def _build_result(self, state: _RunState) -> ReviewResult:
        findings = self._final_findings(state)
        verdicts = self._all_verdicts(state)
        completed_at = datetime.now(UTC)
        if state.failed:
            status = "failed"
        elif state.degraded or state.global_timed_out:
            status = "partial"
        else:
            status = "completed"
        pr = state.pr
        return ReviewResult(
            run_id=state.run_id,
            status=status,
            repository=pr.repository if pr is not None else "未知仓库",
            base_sha=pr.base_sha if pr is not None else "未知",
            head_sha=pr.head_sha if pr is not None else "未知",
            findings=findings,
            rejected_count=sum(not verdict.accepted for verdict in verdicts),
            coverage=sorted({file for context in state.contexts for file in context.files}),
            warnings=list(dict.fromkeys(state.warnings)),
            started_at=state.started_at,
            completed_at=completed_at,
            elapsed_seconds=max(0.0, (completed_at - state.started_at).total_seconds()),
        )

    def _final_findings(self, state: _RunState) -> list[Finding]:
        verdicts = self._all_verdicts(state)
        accepted = [
            verdict.final_finding
            for verdict in verdicts
            if verdict.accepted and verdict.final_finding is not None
        ]
        if accepted:
            return deduplicate_findings(accepted)
        if not (state.verifier_failed or state.global_timed_out):
            return []
        candidates = [finding for snapshot in state.snapshots.values() for finding in snapshot.findings]
        for message in state.blackboard.by_kind("candidate_finding"):
            try:
                candidates.append(Finding.model_validate(message.payload["finding"]))
            except (KeyError, TypeError, ValueError):
                continue
        decided_ids = {verdict.finding_id for verdict in verdicts}
        return deduplicate_findings(
            [
                finding
                for finding in candidates
                if finding.id not in decided_ids and finding.confidence >= 0.8
            ]
        )

    @staticmethod
    def _all_verdicts(state: _RunState) -> list[Verdict]:
        """合并 watcher 返回值和取消前已经发布到 Blackboard 的裁决。"""

        verdicts_by_finding: dict[str, Verdict] = {}
        for message in state.blackboard.by_kind("verdict"):
            try:
                verdict = Verdict.model_validate(message.payload["verdict"])
            except (KeyError, TypeError, ValueError):
                continue
            verdicts_by_finding[verdict.finding_id] = verdict
        for verdict in state.verdicts:
            verdicts_by_finding[verdict.finding_id] = verdict
        return list(verdicts_by_finding.values())

    def _fail_active_stage(self, state: _RunState, reason: str) -> None:
        stage = state.active_stage
        if stage is None or stage in state.terminal_stages:
            return
        self._events.emit(state.run_id, "stage.failed", {"stage": stage, "reason": reason})
        state.terminal_stages.add(stage)
        state.active_stage = None

    @staticmethod
    def _safe_failure_message(error: Exception) -> str:
        """仅暴露已知用户错误；未知异常只报告类型。"""

        if isinstance(error, PRLoadError):
            return f"审查失败：{error}"
        return f"审查流程失败：{type(error).__name__}。"

    @staticmethod
    def _request_mode(request: ReviewRequest) -> str:
        if request.pr_url is not None:
            return "github"
        if request.replay_run_id is not None:
            return "replay"
        return "local"

    @staticmethod
    def _empty_context(pr: PRData) -> ContextPack:
        return ContextPack(
            id="ctx-empty",
            repository=pr.repository,
            base_sha=pr.base_sha,
            head_sha=pr.head_sha,
            pr_title=pr.title,
            pr_description=pr.description,
            files=[],
            diff_hunks=[],
            retrieval_notes=["PR 没有可分片的修改文件。"],
        )

    @staticmethod
    def read_events(runs_dir: str | Path, run_id: str) -> list[PipelineEvent]:
        """读取历史运行事件，供 CLI Replay 和后续服务端复用。"""

        return EventStore(Path(runs_dir)).read(run_id)
