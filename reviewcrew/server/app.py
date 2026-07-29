"""提供可离线注入依赖的 FastAPI 审查服务。"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from reviewcrew.config import Config
from reviewcrew.events import EventStore, PipelineEvent
from reviewcrew.pipeline.orchestrator import Orchestrator
from reviewcrew.redaction import sanitize_persisted_value
from reviewcrew.report import render_markdown
from reviewcrew.schemas import ReviewRequest, ReviewResult
from reviewcrew.server.replay import replay_events, validate_replay_speed


logger = logging.getLogger(__name__)
_TERMINAL_EVENTS = {"review.completed", "review.failed"}


class ReviewOrchestrator(Protocol):
    """服务端需要的最小审查编排协议。"""

    async def review(
        self,
        request: ReviewRequest,
        *,
        run_id: str,
        emit_terminal_event: bool = True,
    ) -> ReviewResult:
        """使用服务端预留的运行标识执行审查。"""


OrchestratorFactory = Callable[[Config, EventStore], ReviewOrchestrator]


@dataclass(slots=True)
class _RunRecord:
    """保存当前进程内后台任务的公开状态。"""

    status: str = "running"
    result: ReviewResult | None = None


def _default_orchestrator(config: Config, event_store: EventStore) -> ReviewOrchestrator:
    return Orchestrator(config, event_store=event_store)


def create_app(
    *,
    config: Config | None = None,
    event_store: EventStore | None = None,
    orchestrator: ReviewOrchestrator | None = None,
    orchestrator_factory: OrchestratorFactory = _default_orchestrator,
    benchmark_results_dir: str | Path = "benchmark/results",
) -> FastAPI:
    """创建应用；编排器、事件存储和目录均可注入以支持纯离线测试。"""

    effective_config = config or Config.from_env()
    store = event_store or EventStore(effective_config.runs_dir)
    benchmark_root = Path(benchmark_results_dir)
    records: dict[str, _RunRecord] = {}
    tasks: set[asyncio.Task[None]] = set()
    active_orchestrator: ReviewOrchestrator | None = orchestrator

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        pending = tuple(tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    app = FastAPI(title="ReviewCrew", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: object, _error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": "审查请求参数无效，请检查后重试。"},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: object, error: StarletteHTTPException) -> JSONResponse:
        detail = error.detail
        if error.status_code == 404 and not isinstance(detail, str):
            detail = "未找到请求的资源。"
        elif error.status_code == 404 and detail == "Not Found":
            detail = "未找到请求的资源。"
        return JSONResponse(status_code=error.status_code, content={"detail": detail})

    def get_orchestrator() -> ReviewOrchestrator:
        nonlocal active_orchestrator
        if active_orchestrator is None:
            active_orchestrator = orchestrator_factory(effective_config, store)
        return active_orchestrator

    async def run_review(run_id: str, request: ReviewRequest) -> None:
        record = records[run_id]
        try:
            result = await _call_review(get_orchestrator(), request, run_id)
            if result.run_id != run_id:
                raise RuntimeError("编排器返回了不一致的运行标识")
            record.result = result
            record.status = result.status
            _emit_terminal_event(store, run_id, result.status)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            record.status = "failed"
            _emit_terminal_event(store, run_id, "failed")
            logger.error(
                "后台审查任务失败：运行=%s，异常类型=%s。",
                run_id,
                type(error).__name__,
            )

    @app.post("/api/reviews", status_code=202)
    async def start_review(request: ReviewRequest) -> dict[str, str]:
        run_id = store.create_run()
        records[run_id] = _RunRecord()
        task = asyncio.create_task(run_review(run_id, request), name=f"reviewcrew-api-{run_id}")
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        await asyncio.sleep(0)
        return {"run_id": run_id, "status": "running"}

    @app.get("/api/reviews/{run_id}")
    async def review_status(run_id: str) -> dict[str, Any]:
        _require_run_directory(store.root, run_id)
        record = records.get(run_id)
        if record is not None and record.result is not None:
            return _public_result(record.result)
        result = _read_result(store.root, run_id)
        if result is not None:
            return _public_result(result)
        if record is not None:
            return {"run_id": run_id, "status": record.status}
        return {"run_id": run_id, "status": _status_from_events(_read_events(store, run_id))}

    @app.get("/api/reviews/{run_id}/events")
    async def review_events(run_id: str) -> StreamingResponse:
        _require_run_directory(store.root, run_id)
        _read_events(store, run_id)
        return _sse_response(_live_events(store, run_id))

    @app.get("/api/reviews/{run_id}/report")
    async def review_report(
        run_id: str,
        format: Literal["json", "markdown"] = Query(default="markdown"),
    ) -> Response:
        run_dir = _require_run_directory(store.root, run_id)
        record = records.get(run_id)
        in_memory_result = record.result if record is not None else None
        if format == "json":
            result = in_memory_result or _read_result(store.root, run_id)
            if result is None:
                raise HTTPException(status_code=404, detail="未找到该运行的 JSON 报告。")
            return JSONResponse(_public_result(result))
        path = run_dir / "report.md"
        if _safe_regular_file(run_dir, path):
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                logger.error(
                    "读取审查报告失败：运行=%s，异常类型=%s。",
                    run_id,
                    type(error).__name__,
                )
                raise HTTPException(
                    status_code=500,
                    detail="审查报告文件损坏，暂时无法读取。",
                ) from None
        elif in_memory_result is not None:
            content = render_markdown(in_memory_result)
        else:
            raise HTTPException(status_code=404, detail="未找到该运行的 Markdown 报告。")
        return Response(content, media_type="text/markdown")

    @app.get("/api/runs")
    async def list_runs(
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        run_summaries: list[tuple[float, str, str]] = []
        if store.root.is_dir():
            for run_dir in store.root.iterdir():
                if (
                    not run_dir.is_dir()
                    or _is_link_like(run_dir)
                    or not _contained_by(store.root, run_dir)
                    or not _valid_run_id(run_dir.name)
                ):
                    continue
                events = _read_events(store, run_dir.name)
                timestamp = (
                    events[-1].timestamp.timestamp() if events else run_dir.stat().st_mtime
                )
                status = (
                    records[run_dir.name].status
                    if run_dir.name in records
                    else _status_from_events(events)
                )
                run_summaries.append((timestamp, run_dir.name, status))
        run_summaries.sort(key=lambda item: (item[0], item[1]), reverse=True)
        summaries = [
            {"run_id": run_id, "status": status}
            for _, run_id, status in run_summaries[offset : offset + limit]
        ]
        return {
            "runs": summaries,
            "total": len(run_summaries),
            "limit": limit,
            "offset": offset,
        }

    @app.get("/api/replays/{run_id}/events")
    async def replay_run_events(
        run_id: str,
        speed: float = Query(default=1.0),
    ) -> StreamingResponse:
        _require_run_directory(store.root, run_id)
        try:
            effective_speed = validate_replay_speed(speed)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        events = _read_events(store, run_id)
        if not events:
            raise HTTPException(status_code=404, detail="该运行没有可回放的事件。")
        return _sse_response(replay_events(events, speed=effective_speed))

    @app.get("/api/benchmarks/latest")
    async def latest_benchmark() -> JSONResponse:
        payload = _read_latest_benchmark(benchmark_root)
        if payload is None:
            raise HTTPException(status_code=404, detail="未找到可用的评测摘要。")
        return JSONResponse(payload)

    return app


async def _call_review(
    orchestrator: ReviewOrchestrator,
    request: ReviewRequest,
    run_id: str,
) -> ReviewResult:
    """调用新协议，并为简单 Fake 保留明确的签名兼容错误。"""

    review = orchestrator.review
    parameters = inspect.signature(review).parameters
    accepts_keywords = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    if "run_id" not in parameters and not accepts_keywords:
        raise TypeError("注入的编排器 review 方法必须接受 run_id 关键字参数")
    arguments: dict[str, Any] = {"run_id": run_id}
    if "emit_terminal_event" in parameters or accepts_keywords:
        arguments["emit_terminal_event"] = False
    return await review(request, **arguments)


def _emit_terminal_event(store: EventStore, run_id: str, status: str) -> None:
    """由 HTTP 后台任务在真实完成或失败后发送唯一终态。"""

    desired_type = "review.failed" if status == "failed" else "review.completed"
    store.emit(run_id, desired_type, {"status": status})


def _valid_run_id(run_id: str) -> bool:
    return bool(run_id) and Path(run_id).name == run_id and not any(
        token in run_id for token in ("/", "\\", "..")
    )


def _require_run_directory(root: Path, run_id: str) -> Path:
    """解析固定运行目录，拒绝路径穿越、符号链接和不存在的运行。"""

    if not _valid_run_id(run_id):
        raise HTTPException(status_code=404, detail="未找到指定的运行。")
    run_dir = Path(root) / run_id
    if (
        not run_dir.is_dir()
        or _is_link_like(run_dir)
        or not _contained_by(Path(root), run_dir)
    ):
        raise HTTPException(status_code=404, detail="未找到指定的运行。")
    return run_dir


def _read_result(root: Path, run_id: str) -> ReviewResult | None:
    run_dir = _require_run_directory(root, run_id)
    path = run_dir / "result.json"
    if not path.exists():
        return None
    if not _safe_regular_file(run_dir, path):
        raise HTTPException(status_code=404, detail="未找到该运行的 JSON 报告。")
    try:
        return ReviewResult.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        logger.error("读取审查结果失败：运行=%s，异常类型=%s。", run_id, type(error).__name__)
        raise HTTPException(status_code=500, detail="审查结果文件损坏，暂时无法读取。") from None


def _read_events(store: EventStore, run_id: str) -> list[PipelineEvent]:
    """在 HTTP 边界将损坏事件文件转换为安全的中文错误。"""

    try:
        return store.read(run_id)
    except (OSError, ValueError) as error:
        logger.error("读取审查事件失败：运行=%s，异常类型=%s。", run_id, type(error).__name__)
        raise HTTPException(
            status_code=500,
            detail="审查事件文件损坏，暂时无法读取。",
        ) from None


def _public_result(result: ReviewResult) -> dict[str, Any]:
    return sanitize_persisted_value(result.model_dump(mode="json"))


def _is_link_like(path: Path) -> bool:
    """识别符号链接和 Windows Junction 等目录重解析点。"""

    return path.is_symlink() or path.is_junction()


def _contained_by(root: Path, candidate: Path) -> bool:
    """确认解析后的路径仍位于固定根目录内。"""

    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


def _safe_regular_file(root: Path, path: Path) -> bool:
    return (
        path.is_file()
        and not _is_link_like(path)
        and _contained_by(root, path)
    )


def _status_from_events(events: list[PipelineEvent]) -> str:
    for event in reversed(events):
        if event.type == "review.failed":
            return "failed"
        if event.type == "review.completed":
            return str(event.data.get("status", "completed"))
    return "running"


def _public_event(event: PipelineEvent) -> dict[str, Any]:
    """冻结 SSE 输出为脱敏后的 PipelineEvent 六个公开字段。"""

    payload = event.model_dump(mode="json")
    payload["data"] = sanitize_persisted_value(payload["data"])
    return payload


def _encode_sse(event: PipelineEvent) -> str:
    return f"data: {json.dumps(_public_event(event), ensure_ascii=False, separators=(',', ':'))}\n\n"


def _sse_response(events: AsyncIterator[PipelineEvent]) -> StreamingResponse:
    async def encoded() -> AsyncIterator[str]:
        async for event in events:
            yield _encode_sse(event)

    return StreamingResponse(
        encoded(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _live_events(
    store: EventStore,
    run_id: str,
) -> AsyncIterator[PipelineEvent]:
    """先注册实时订阅，再补持久化历史；重叠窗口按序号去重。"""

    subscription = store.subscribe(run_id)
    pending = asyncio.create_task(anext(subscription), name=f"reviewcrew-sse-{run_id}")
    await asyncio.sleep(0)
    seen_sequences: set[int] = set()
    try:
        persisted = sorted(_read_events(store, run_id), key=lambda item: item.sequence)
        last_persisted_terminal = next(
            (event.sequence for event in reversed(persisted) if event.type in _TERMINAL_EVENTS),
            None,
        )
        for event in persisted:
            if event.sequence in seen_sequences:
                continue
            if event.type in _TERMINAL_EVENTS and event.sequence != last_persisted_terminal:
                continue
            seen_sequences.add(event.sequence)
            yield event
            if event.sequence == last_persisted_terminal:
                return

        while True:
            try:
                event = await pending
            except StopAsyncIteration:
                return
            pending = asyncio.create_task(anext(subscription), name=f"reviewcrew-sse-{run_id}")
            if event.sequence in seen_sequences:
                continue
            seen_sequences.add(event.sequence)
            yield event
            if event.type in _TERMINAL_EVENTS:
                return
    finally:
        if not pending.done():
            pending.cancel()
        with suppress(asyncio.CancelledError, StopAsyncIteration):
            await pending
        with suppress(RuntimeError):
            await subscription.aclose()


def _read_latest_benchmark(root: Path) -> dict[str, Any] | None:
    """从固定评测目录或时间戳子目录返回最近的 JSON 摘要。"""

    if not root.is_dir() or root.is_symlink():
        return None
    direct_summary = root / "summary.json"
    nested_summaries = (
        child / "summary.json"
        for child in root.iterdir()
        if child.is_dir() and not _is_link_like(child) and _contained_by(root, child)
    )
    candidates = sorted(
        (
            path
            for path in (direct_summary, *nested_summaries)
            if _safe_regular_file(root, path)
        ),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            return sanitize_persisted_value(payload)
    return None


app = create_app()
