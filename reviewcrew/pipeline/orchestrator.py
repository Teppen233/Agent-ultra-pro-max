"""确定性编排 PR 加载、上下文、Agent Team、验证和报告持久化。"""

from __future__ import annotations

import asyncio
import inspect
import multiprocessing
import pickle
import shutil
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from reviewcrew.agents.defect import DefectAgent
from reviewcrew.agents.intent import IntentAgent
from reviewcrew.agents.team_lead import TeamLeadAgent
from reviewcrew.agents.verifier import VerifierAgent
from reviewcrew.budget import ReviewBudget
from reviewcrew.config import Config
from reviewcrew.context.builder import build_context
from reviewcrew.events import EventStore, PipelineEvent
from reviewcrew.github.pr_loader import PRLoadError, load_pr
from reviewcrew.pipeline.dedupe import deduplicate_findings
from reviewcrew.redaction import sanitize_persisted_value
from reviewcrew.report import persist_report, render_markdown
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
from reviewcrew.tool_activity import ToolActivityPublisher


PRLoader = Callable[[ReviewRequest, Config], Awaitable[PRData]]
ContextBuilder = Callable[..., Awaitable[list[ContextPack]]]
StaticAnalyzer = Callable[[PRData, list[ContextPack]], Awaitable[list[StaticSignal]]]
AgentFactory = Callable[[MessagePublisher], object]
ReportPersister = Callable[[ReviewResult, str | Path], tuple[Path, Path]]
ReportRenderer = Callable[[ReviewResult], str]

_REPORT_FALLBACK_RESERVE_SECONDS = 12.0
_TERMINAL_EVENT_RESERVE_SECONDS = 8.0
_FINAL_CORRECTION_RESERVE_SECONDS = 4.0
_PROCESS_CLEANUP_RESERVE_SECONDS = 0.5


def _execute_sync_operation(sender: Any, operation: Callable[..., Any], arguments: tuple[Any, ...]) -> None:
    """在隔离进程执行同步操作，并只回传结构化成功或失败结果。"""

    try:
        sender.send((True, operation(*arguments)))
    except BaseException as error:
        sender.send((False, type(error).__name__))
    finally:
        sender.close()


def _emit_events_from_root(
    root: Path,
    run_id: str,
    events: list[tuple[str, dict[str, Any]]],
) -> list[PipelineEvent]:
    """在隔离进程批量持久化报告和终态事件。"""

    store = EventStore(root)
    return [store.emit(run_id, event_type, data) for event_type, data in events]


def _persist_and_promote_report(
    operation: ReportPersister,
    result: ReviewResult,
    staging_root: Path,
    target_root: Path,
    run_id: str,
) -> None:
    """在隔离进程完成持久化、路径校验、原子提升和清理。"""

    try:
        paths = operation(result, staging_root)
        staging_directory = (staging_root / run_id).resolve()
        target_directory = target_root / run_id
        target_directory.mkdir(parents=True, exist_ok=True)
        for source in paths:
            resolved = Path(source).resolve()
            if resolved.parent != staging_directory or resolved.name not in {"result.json", "report.md"}:
                raise ValueError("报告持久化器返回了隔离目录之外的路径")
            resolved.replace(target_directory / resolved.name)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def _cleanup_report_staging(staging_root: Path) -> None:
    """清理由已终止报告进程遗留的隔离目录。"""

    shutil.rmtree(staging_root, ignore_errors=True)


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
    tools: ToolActivityPublisher
    deadline_monotonic: float
    pr: PRData | None = None
    budget: ReviewBudget | None = None
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
        recipient = arguments["recipient"]
        correlation_id = arguments.get("correlation_id")
        public_kind = {
            "candidate_finding": "candidate_finding",
            "verification_request": "evidence_request",
            "evidence_response": "evidence_response",
            "verdict": "verifier_final",
            "agent_review_completed": "agent_review_completed",
        }.get(kind)
        if public_kind is not None:
            self._events.emit(
                self.run_id,
                "mailbox.message",
                {
                    "sender": sender,
                    "recipient": recipient,
                    "kind": public_kind,
                    "correlation_id": correlation_id,
                    "summary": self._mailbox_summary(kind, payload),
                },
            )
        if kind == "candidate_finding":
            finding = payload.get("finding", {})
            self._events.emit(
                self.run_id,
                "agent.candidate",
                sanitize_persisted_value({
                    "agent": sender,
                    "finding_id": finding.get("id"),
                    "file": finding.get("file"),
                    "line": finding.get("line_start"),
                    "severity": finding.get("severity"),
                }),
            )
        elif kind in {"agent_completed", "agent_failed"}:
            event_type = "agent.completed" if kind == "agent_completed" else "agent.failed"
            self._events.emit(
                self.run_id,
                event_type,
                sanitize_persisted_value({
                    "agent": payload.get("agent_id", sender),
                    "role": payload.get("role"),
                    "warning": payload.get("warning"),
                }),
            )
        elif kind == "verdict":
            verdict = payload.get("verdict", {})
            event_type = "verifier.accepted" if verdict.get("accepted") else "verifier.rejected"
            self._events.emit(
                self.run_id,
                event_type,
                sanitize_persisted_value({
                    "finding_id": verdict.get("finding_id"),
                    "verdict": verdict.get("verdict"),
                    "confidence": verdict.get("confidence"),
                }),
            )
        return True

    @staticmethod
    def _mailbox_summary(kind: str, payload: dict[str, Any]) -> str:
        """只从结构化标识生成短摘要，不复述任意消息正文。"""

        if kind == "candidate_finding":
            finding = payload.get("finding", {})
            return (
                f"发布 {finding.get('severity') or '未知级别'} 候选 "
                f"{finding.get('file') or '未知文件'}:{finding.get('line_start') or '?'}"
            )
        if kind == "verification_request":
            return f"请求补充候选 {payload.get('finding_id') or '未知'} 的结构化证据"
        if kind == "evidence_response":
            evidence = payload.get("evidence", [])
            return (
                f"返回 {len(evidence) if isinstance(evidence, list) else 0} 条补充证据，"
                f"结论为 {payload.get('conclusion') or 'unknown'}"
            )
        if kind == "verdict":
            verdict = payload.get("verdict", {})
            outcome = "接受" if verdict.get("accepted") else "拒绝"
            return f"{outcome}候选 {verdict.get('finding_id') or '未知'}"
        return (
            f"专家 {payload.get('agent_id') or '未知'} 已完成上下文 "
            f"{payload.get('context_id') or '未知'} 的审查"
        )


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
        report_renderer: ReportRenderer = render_markdown,
        stage_timeouts: Mapping[str, float] | None = None,
        global_timeout_seconds: float | None = None,
        budget_grace_seconds: float = 5.0,
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
        self._render_report = report_renderer
        configured_global_timeout = (
            float(self.config.global_timeout_seconds)
            if global_timeout_seconds is None or global_timeout_seconds == 0
            else float(global_timeout_seconds)
        )
        self._global_timeout = min(configured_global_timeout, 600.0)
        self._budget_grace_seconds = max(0.0, budget_grace_seconds)
        self._timeouts = {
            "loading_pr": float(self.config.pr_load_timeout_seconds),
            "building_context": float(self.config.context_timeout_seconds),
            "planning": float(self.config.review_timeout_seconds),
            "team_review": float(self.config.global_timeout_seconds),
            "verifier": float(self.config.verifier_timeout_seconds),
            "reporting": float(self.config.report_timeout_seconds),
            **dict(stage_timeouts or {}),
        }

    async def review(
        self,
        request: ReviewRequest,
        *,
        run_id: str | None = None,
        emit_terminal_event: bool = True,
    ) -> ReviewResult:
        """执行一次审查，并在任何超时路径上返回已持久化的 ReviewResult。"""

        if run_id is None:
            run_id = self._events.create_run()
        # 服务端可先预留目录并返回稳定 ID；无论来源如何都必须原子 claim 一次。
        self._events.claim_run(run_id)
        started_at = datetime.now(UTC)
        mailbox = Mailbox(self.config.runs_dir, run_id)
        blackboard = EvidenceBlackboard(run_id)
        publisher = _EventingPublisher(mailbox=mailbox, blackboard=blackboard, events=self._events)
        tools = ToolActivityPublisher(self._events, run_id)
        deadline_monotonic = time.monotonic() + self._global_timeout
        state = _RunState(
            run_id=run_id,
            started_at=started_at,
            mailbox=mailbox,
            blackboard=blackboard,
            publisher=publisher,
            tools=tools,
            deadline_monotonic=deadline_monotonic,
        )
        started_data = {"mode": self._request_mode(request)}
        if request.repo_path is not None:
            started_data.update(
                {
                    "repository": Path(request.repo_path).resolve().name,
                    "title": f"本地审查 {request.base_ref} → {request.head_ref}",
                }
            )
        self._events.emit(run_id, "review.started", started_data)

        try:
            async with asyncio.timeout(self._global_timeout):
                await self._run_core(request, state)
        except StageTimeoutError as error:
            state.degraded = True
            if error.stage == "team_review":
                state.verifier_failed = True
                self._consume_agent_snapshots(state)
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

        result, report_generated, report_failed, report_reason = await self._finalize_report(state)
        final_type = "review.failed" if result.status == "failed" else "review.completed"
        terminal_events: list[tuple[str, dict[str, Any]]] = [("stage.started", {"stage": "reporting"})]
        if report_failed:
            terminal_events.append(("stage.failed", {"stage": "reporting", "reason": report_reason}))
        else:
            terminal_events.append(("stage.completed", {"stage": "reporting"}))
        if report_generated:
            terminal_events.append(("report.generated", {"status": result.status}))
        if emit_terminal_event:
            terminal_events.append((final_type, {"status": result.status}))
        terminal_deadline = self._reserved_deadline(
            state.deadline_monotonic,
            _FINAL_CORRECTION_RESERVE_SECONDS,
        )
        try:
            await self._emit_events_until(run_id, terminal_events, terminal_deadline)
        except (TimeoutError, RuntimeError):
            state.degraded = True
            state.global_timed_out = True
            state.warnings.append("终态事件超过全局截止时间，已返回当前部分结果。")
            result = self._build_result(state)
            await self._persist_partial_fallback(result, state.deadline_monotonic)
        return result

    async def _finalize_report(
        self,
        state: _RunState,
    ) -> tuple[ReviewResult, bool, bool, str]:
        """在共享截止时间内完成报告最终化，超时则保存 partial 快照。"""

        stage = "reporting"
        state.active_stage = stage
        started = time.perf_counter()
        draft = self._build_result(state)
        generation_error: Exception | None = None
        report_deadline = min(
            self._reserved_deadline(
                state.deadline_monotonic,
                _REPORT_FALLBACK_RESERVE_SECONDS,
            ),
            time.monotonic() + self._timeouts[stage],
        )
        exceeded = False
        try:
            await self._run_sync_until(
                report_deadline,
                self._render_report,
                draft,
            )
        except TimeoutError:
            exceeded = True
        except Exception as error:
            generation_error = error

        exceeded = exceeded or time.perf_counter() - started > self._timeouts[stage]
        if exceeded:
            state.degraded = True
            state.warnings.append("报告生成阶段超时，已保存当前部分结果。")
        if generation_error is not None:
            state.degraded = True
            state.warnings.append(f"报告生成失败：{type(generation_error).__name__}。")

        result = self._build_result(state)
        generated = True
        if exceeded:
            result = self._build_result(state)
            generated = await self._persist_partial_fallback(
                result,
                self._reserved_deadline(
                    state.deadline_monotonic,
                    _TERMINAL_EVENT_RESERVE_SECONDS,
                ),
            )
        else:
            try:
                await self._persist_report_until(state, result, report_deadline)
            except TimeoutError:
                exceeded = True
                state.degraded = True
                state.warnings.append("报告持久化超过全局截止时间，已保存当前部分结果。")
                result = self._build_result(state)
                generated = await self._persist_partial_fallback(
                    result,
                    self._reserved_deadline(
                        state.deadline_monotonic,
                        _TERMINAL_EVENT_RESERVE_SECONDS,
                    ),
                )
            except Exception as error:
                generated = False
                state.degraded = True
                state.warnings.append(f"报告最终提交失败：{type(error).__name__}。")
                result = self._build_result(state)

        state.terminal_stages.add(stage)
        state.active_stage = None
        report_failed = exceeded or generation_error is not None or not generated
        report_reason = "timeout" if exceeded else "persist_failed"
        return result, generated, report_failed, report_reason

    async def _run_sync_until(
        self,
        deadline_monotonic: float,
        operation: Callable[..., Any],
        *arguments: Any,
    ) -> Any:
        """在可终止的隔离进程运行同步操作，截止后不遗留后台任务。"""

        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        try:
            pickle.dumps((operation, arguments))
        except (AttributeError, pickle.PickleError, TypeError):
            raise TimeoutError from None

        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=_execute_sync_operation,
            args=(sender, operation, arguments),
            daemon=True,
        )
        try:
            process.start()
            sender.close()
            execution_deadline = self._reserved_deadline(
                deadline_monotonic,
                _PROCESS_CLEANUP_RESERVE_SECONDS,
            )
            remaining = max(0.0, execution_deadline - time.monotonic())
            await asyncio.to_thread(process.join, remaining)
            if process.is_alive():
                process.terminate()
                cleanup_remaining = max(0.0, deadline_monotonic - time.monotonic())
                await asyncio.to_thread(process.join, cleanup_remaining / 2)
                if process.is_alive():
                    process.kill()
                    cleanup_remaining = max(0.0, deadline_monotonic - time.monotonic())
                    await asyncio.to_thread(process.join, cleanup_remaining)
                raise TimeoutError
            if not receiver.poll():
                raise RuntimeError("隔离的报告操作未返回结果")
            succeeded, payload = receiver.recv()
            if not succeeded:
                raise RuntimeError(f"隔离的报告操作失败：{payload}")
            return payload
        finally:
            receiver.close()
            sender.close()
            if not process.is_alive():
                process.close()

    @staticmethod
    def _reserved_deadline(deadline_monotonic: float, reserve_seconds: float) -> float:
        """在绝对截止时间内划出明确清理预留，短测试窗口按比例缩放。"""

        remaining = max(0.0, deadline_monotonic - time.monotonic())
        reserve = min(reserve_seconds, remaining / 2)
        return deadline_monotonic - reserve

    async def _persist_report_until(
        self,
        state: _RunState,
        result: ReviewResult,
        deadline_monotonic: float,
    ) -> None:
        """在隔离目录运行持久化器，成功后才将产物提升到正式目录。"""

        staging_root = Path(self.config.runs_dir) / f".report-staging-{state.run_id}-{uuid4().hex}"
        activity = state.tools.started(
            actor="reporter",
            actor_type="system",
            tool_name="report.persist",
            target=state.run_id,
        )
        try:
            await self._run_sync_until(
                deadline_monotonic,
                _persist_and_promote_report,
                self._persist_report,
                result,
                staging_root,
                Path(self.config.runs_dir),
                state.run_id,
            )
        except Exception:
            activity.fail("报告持久化失败，未发布成功事件")
            raise
        else:
            finding_count = len(result.findings)
            activity.complete(
                f"已保存 JSON 和 Markdown 报告，共 {finding_count} 个 Finding",
                result_count=finding_count,
            )
        finally:
            if staging_root.exists():
                cleanup_deadline = self._reserved_deadline(
                    state.deadline_monotonic,
                    _TERMINAL_EVENT_RESERVE_SECONDS,
                )
                try:
                    await self._run_sync_until(
                        cleanup_deadline,
                        _cleanup_report_staging,
                        staging_root,
                    )
                except (TimeoutError, RuntimeError):
                    pass

    async def _persist_partial_fallback(
        self,
        result: ReviewResult,
        deadline_monotonic: float,
    ) -> bool:
        """在绝对截止时间内使用内置原子持久化器保存 partial 快照。"""

        activity = ToolActivityPublisher(self._events, result.run_id).started(
            actor="reporter",
            actor_type="system",
            tool_name="report.persist",
            target=result.run_id,
            summary="保存部分审查快照",
        )
        try:
            await self._run_sync_until(
                deadline_monotonic,
                persist_report,
                result,
                self.config.runs_dir,
            )
        except (TimeoutError, RuntimeError):
            activity.fail("部分报告持久化失败，未发布成功事件")
            return False
        activity.complete(
            f"已保存部分审查快照，共 {len(result.findings)} 个 Finding",
            result_count=len(result.findings),
        )
        return True

    async def _emit_events_until(
        self,
        run_id: str,
        events: list[tuple[str, dict[str, Any]]],
        deadline_monotonic: float,
    ) -> None:
        """在绝对截止时间内批量写入事件，并同步父进程订阅状态。"""

        emitted = await self._run_sync_until(
            deadline_monotonic,
            _emit_events_from_root,
            self._events.root,
            run_id,
            events,
        )
        if emitted:
            self._events._sequences[run_id] = emitted[-1].sequence
        for event in emitted:
            for queue in tuple(self._events._subscribers[run_id]):
                queue.put_nowait(event)

    async def _run_core(self, request: ReviewRequest, state: _RunState) -> None:
        state.pr = await self._run_stage(
            state,
            "loading_pr",
            lambda: self._call_with_supported_keywords(
                self._pr_loader,
                request,
                self.config,
                activity=state.tools,
            ),
        )
        state.budget = ReviewBudget.from_pr(
            state.pr,
            self.config,
            deadline_monotonic=state.deadline_monotonic,
        )
        state.contexts = await self._run_stage(
            state,
            "building_context",
            lambda: self._call_context_builder(state.pr, request, state.tools),
        )
        for context in state.contexts:
            await state.publisher.publish(
                sender="orchestrator",
                recipient="*",
                kind="context_available",
                key=f"context:{context.id}",
                payload={"context_id": context.id, "files": context.files},
            )
        planning_budget = Budget(seconds=self._stage_budget_seconds(state, "planning"))
        state.plan = await self._run_stage(
            state,
            "planning",
            lambda: self._team_lead.plan(state.pr, state.contexts, planning_budget),
        )
        self._events.emit(
            state.run_id,
            "plan.published",
            state.plan.model_dump(mode="json"),
        )
        await state.publisher.publish(
            sender="team_lead",
            recipient="*",
            kind="review_plan",
            key="review-plan",
            payload=state.plan.model_dump(mode="json"),
        )
        await self._run_stage(state, "team_review", lambda: self._run_team(state))

    def _stage_budget_seconds(self, state: _RunState, stage: str) -> int:
        """从同一绝对截止时间派生阶段预算，并为报告预留时间。"""

        return max(1, int(self._stage_timeout_seconds(state, stage)))

    def _stage_timeout_seconds(self, state: _RunState, stage: str) -> float:
        """返回阶段实际可用时长，保留测试可注入的亚秒超时精度。"""

        reserve_seconds = 20.0 if stage != "reporting" and self._global_timeout >= 20 else 0.0
        remaining = max(0.0, state.deadline_monotonic - time.monotonic() - reserve_seconds)
        configured = self._timeouts[stage]
        if stage == "team_review" and state.budget is not None:
            configured = min(configured, float(state.budget.team_soft_seconds))
        return min(configured, remaining)

    async def _run_team(self, state: _RunState) -> None:
        if state.pr is None or state.plan is None:
            return
        contexts = state.contexts or [self._empty_context(state.pr)]
        work_items = self._planned_work_items(state.plan, contexts)
        expected_agent_ids = {f"{role}:{context.id}" for role, context in work_items}
        stop_event = asyncio.Event()
        semaphore = asyncio.Semaphore(self.config.max_concurrency)
        team_timeout_seconds = self._stage_timeout_seconds(state, "team_review")
        team_budget_seconds = self._stage_budget_seconds(state, "team_review")
        watcher_task: asyncio.Task[list[Verdict] | None] | None = None
        expert_tasks: list[asyncio.Task[AgentSnapshot | None]] = []
        static_task: asyncio.Task[None] | None = None
        budget_task: asyncio.Task[None] | None = None
        try:
            async with asyncio.TaskGroup() as group:
                watcher_task = group.create_task(
                    self._run_verifier(state, expected_agent_ids, stop_event, team_budget_seconds),
                    name="reviewcrew-verifier",
                )
                factories = {"defect": self._defect_factory, "intent": self._intent_factory}
                for role, context in work_items:
                    expert_tasks.append(
                        group.create_task(
                            self._run_expert(state, role, factories[role], context, semaphore),
                            name=f"reviewcrew-{role}-{context.id}",
                        )
                    )
                if self._static_analyzer is not None:
                    static_task = group.create_task(
                        self._run_static_analyzer(state, semaphore),
                        name="reviewcrew-static",
                    )
                budget_task = group.create_task(
                    self._warn_and_collect_before_deadline(state, expected_agent_ids, team_timeout_seconds),
                    name="reviewcrew-budget-warning",
                )
                group.create_task(
                    self._stop_watcher_after_experts(expert_tasks, stop_event, budget_task),
                    name="reviewcrew-watcher-stop",
                )
        finally:
            stop_event.set()
            if watcher_task is not None and not watcher_task.done():
                watcher_task.cancel()
            if static_task is not None and not static_task.done():
                static_task.cancel()
            if budget_task is not None and not budget_task.done():
                budget_task.cancel()
            self._consume_agent_snapshots(state)

    @staticmethod
    def _planned_work_items(
        plan: ReviewPlan,
        contexts: list[ContextPack],
    ) -> list[tuple[str, ContextPack]]:
        """将 Team Lead 的角色与 shard 计划解析为稳定、去重的实例工作项。"""

        contexts_by_id = {context.id: context for context in contexts}
        fallback_ids = [context_id for context_id in plan.context_ids if context_id in contexts_by_id]
        work_items: list[tuple[str, ContextPack]] = []
        seen: set[tuple[str, str]] = set()
        for role in plan.required_agents:
            planned_ids = [
                context_id
                for shard, context_ids in plan.shards.items()
                if shard == role or shard.startswith(f"{role}:")
                for context_id in context_ids
                if context_id in contexts_by_id
            ]
            for context_id in planned_ids or fallback_ids:
                key = (role, context_id)
                if key in seen:
                    continue
                seen.add(key)
                work_items.append((role, contexts_by_id[context_id]))
        return work_items

    async def _run_expert(
        self,
        state: _RunState,
        role: str,
        factory: AgentFactory,
        context: ContextPack,
        semaphore: asyncio.Semaphore,
    ) -> AgentSnapshot | None:
        agent_id = f"{role}:{context.id}"
        self._events.emit(
            state.run_id,
            "agent.started",
            {
                "agent": agent_id,
                "role": role,
                "context_id": context.id,
                "files": context.files,
            },
        )
        agent = factory(state.publisher)
        budget = Budget(seconds=self._stage_budget_seconds(state, "team_review"))
        try:
            async with semaphore:
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
            self._consume_agent_snapshots(state)
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
        team_budget_seconds: int,
    ) -> list[Verdict] | None:
        self._events.emit(state.run_id, "verifier.started", {"agent": "verifier"})
        verifier = self._verifier_factory(state.publisher)
        budget = Budget(seconds=team_budget_seconds)
        try:
            verdicts = await verifier.watch(
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
            await self._publish_verifier_failure_if_missing(state)
            return None

    async def _run_static_analyzer(
        self,
        state: _RunState,
        semaphore: asyncio.Semaphore,
    ) -> None:
        if self._static_analyzer is None or state.pr is None:
            return
        try:
            async with semaphore:
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
        budget_task: asyncio.Task[None],
    ) -> None:
        await asyncio.gather(*expert_tasks, return_exceptions=True)
        self._consume_agent_snapshots_from_tasks(expert_tasks)
        stop_event.set()
        if not budget_task.done():
            budget_task.cancel()

    def _consume_agent_snapshots_from_tasks(
        self,
        expert_tasks: list[asyncio.Task[AgentSnapshot | None]],
    ) -> None:
        """确保协调器读取任务异常前不遗漏已经完成的快照。"""

        for task in expert_tasks:
            if task.cancelled() or not task.done():
                continue
            try:
                task.result()
            except Exception:
                continue

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

    async def _warn_and_collect_before_deadline(
        self,
        state: _RunState,
        expected_agent_ids: set[str],
        team_timeout_seconds: float,
    ) -> None:
        """在团队预算到期前发送预警，并在 grace 窗口持续消费快照。"""

        grace = min(self._budget_grace_seconds, team_timeout_seconds)
        await asyncio.sleep(max(0.0, team_timeout_seconds - grace))
        terminal_ids = {
            message.payload.get("agent_id")
            for message in state.blackboard.messages
            if message.kind in {"agent_completed", "agent_failed"}
        }
        for agent_id in sorted(expected_agent_ids - terminal_ids):
            role = agent_id.split(":", 1)[0]
            await state.publisher.publish(
                sender="orchestrator",
                recipient=agent_id,
                kind="budget_warning",
                key=f"budget:{agent_id}",
                payload={"agent_id": agent_id, "role": role, "request_snapshot": True},
            )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + grace
        try:
            while loop.time() < deadline:
                self._consume_agent_snapshots(state)
                await asyncio.sleep(min(0.005, max(0.0, deadline - loop.time())))
        finally:
            self._consume_agent_snapshots(state)

    def _consume_agent_snapshots(self, state: _RunState) -> None:
        """验证并合并 Blackboard 中由预算预警触发的 AgentSnapshot。"""

        for message in state.blackboard.by_kind("agent_snapshot"):
            payload = message.payload.get("snapshot", message.payload)
            try:
                snapshot = AgentSnapshot.model_validate(payload)
            except (TypeError, ValueError):
                continue
            state.snapshots[snapshot.agent_id] = snapshot

    async def _publish_verifier_failure_if_missing(self, state: _RunState) -> None:
        """仅在 watcher 没有自行发布失败终态时补发一次。"""

        if any(
            message.kind in {"agent_completed", "agent_failed"}
            and message.payload.get("agent_id") == "verifier"
            for message in state.blackboard.messages
        ):
            return
        await state.publisher.publish(
            sender="verifier",
            recipient="*",
            kind="agent_failed",
            key="failed",
            payload={"agent_id": "verifier", "role": "verifier", "warning": "Verifier 执行未完成。"},
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
            async with asyncio.timeout(self._stage_timeout_seconds(state, stage)):
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
        activity: ToolActivityPublisher,
    ) -> list[ContextPack]:
        return await self._call_with_supported_keywords(
            self._context_builder,
            pr,
            request,
            self.config,
            request=request,
            config=self.config,
            activity=activity,
        )

    async def _default_context_builder(
        self,
        pr: PRData,
        request: ReviewRequest,
        config: Config,
        activity: ToolActivityPublisher | None = None,
    ) -> list[ContextPack]:
        if request.repo_path is not None:
            return await build_context(
                pr,
                Path(request.repo_path).resolve(),
                config,
                activity=activity,
            )
        if activity is not None:
            target = pr.repository
            for tool_name, capability in (
                ("context.read_docs", "项目文档读取"),
                ("context.read_file", "文件范围读取"),
                ("context.find_tests", "相关测试检索"),
                ("context.search_symbol", "符号引用检索"),
                ("static.semgrep", "Semgrep 静态扫描"),
            ):
                activity.degraded(
                    actor="context_builder",
                    actor_type="system",
                    tool_name=tool_name,
                    target=target,
                    summary=f"GitHub 模式未配置本地仓库，{capability}已降级",
                )
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
