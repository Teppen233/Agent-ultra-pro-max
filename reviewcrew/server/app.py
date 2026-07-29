"""FastAPI 服务 —— REST/SSE 接口和后台审查任务管理。

提供：
- POST /api/reviews — 启动审查
- GET /api/reviews/{run_id} — 查询状态
- GET /api/reviews/{run_id}/events — SSE 事件流
- GET /api/reviews/{run_id}/report — 获取报告
- GET /api/runs — 历史运行列表
- GET /api/replays/{run_id}/events — 事件回放
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

from ..config import Config
from ..events import EventStore
from ..schemas import ReviewRequest, ReviewResult, ErrorResponse, PipelineEvent
from ..pipeline.orchestrator import Orchestrator
from .replay import replay_events

logger = logging.getLogger(__name__)

app = FastAPI(
    title="ReviewCrew API",
    description="AI Code Review 系统 HTTP 接口",
    version="0.1.0",
)

# 全局状态
_config: Config | None = None
_store: EventStore | None = None
_orchestrator: Orchestrator | None = None
_tasks: dict[str, asyncio.Task] = {}


def init_app(config: Config) -> None:
    """初始化应用全局状态。"""
    global _config, _store, _orchestrator
    _config = config
    _store = EventStore(config.runs_dir)
    _orchestrator = Orchestrator(config, _store)


def _get_orchestrator() -> Orchestrator:
    """获取 Orchestrator 实例（懒初始化）。"""
    global _orchestrator, _config, _store
    if _orchestrator is None:
        _config = Config.from_env()
        _store = EventStore(_config.runs_dir)
        _orchestrator = Orchestrator(_config, _store)
    return _orchestrator


def _get_store() -> EventStore:
    """获取 EventStore 实例。"""
    global _store, _config
    if _store is None:
        _config = Config.from_env()
        _store = EventStore(_config.runs_dir)
    return _store


# ---- REST 接口 ----

@app.post("/api/reviews")
async def start_review(request: ReviewRequest):
    """启动一次代码审查（异步后台任务）。"""
    orch = _get_orchestrator()
    store = _get_store()

    # 如果是 Replay 模式，直接返回已有的运行
    if request.replay_run_id:
        events = store.read(request.replay_run_id)
        if not events:
            raise HTTPException(
                status_code=404,
                detail=f"Replay 运行不存在: {request.replay_run_id}",
            )
        return {"run_id": request.replay_run_id, "mode": "replay"}

    # 预创建 run_id 并发射启动事件，这样前端可立即开始轮询
    run_id = store.create_run()
    store.emit(run_id, "review.started", {
        "run_id": run_id,
        "repo": request.pr_url or request.repo_path or "",
    })

    # 在后台启动审查
    async def _run_and_emit() -> None:
        try:
            result = await orch.review_with_run_id(run_id, request)
        except Exception as e:
            logger.exception("后台审查异常")
            store.emit(run_id, "review.failed", {
                "run_id": run_id,
                "reason": f"审查异常: {e}",
            })

    asyncio.create_task(_run_and_emit())

    return {"run_id": run_id, "mode": "live"}


@app.get("/api/reviews/{run_id}")
async def get_review_status(run_id: str):
    """查询审查运行的状态。"""
    store = _get_store()
    events = store.read(run_id)
    if not events:
        raise HTTPException(
            status_code=404,
            detail=f"运行不存在: {run_id}",
        )

    # 从事件推断状态
    completed = any(e.type == "review.completed" for e in events)
    failed = any(e.type == "review.failed" for e in events)

    if completed:
        status = "completed"
    elif failed:
        status = "failed"
    else:
        status = "running"

    return {
        "run_id": run_id,
        "status": status,
        "event_count": len(events),
    }


@app.get("/api/reviews/{run_id}/events")
async def stream_events(run_id: str, request: Request):
    """SSE 事件流 —— 实时推送审查进度。"""
    store = _get_store()

    async def event_generator() -> AsyncIterator[dict]:
        last_seq = 0
        while True:
            if await request.is_disconnected():
                break

            events = store.read(run_id)
            new_events = [e for e in events if e.sequence > last_seq]

            for event in new_events:
                last_seq = event.sequence
                yield {
                    "event": event.type,
                    "data": event.model_dump_json(),
                }

            # 检查是否已完成
            if any(e.type in ("review.completed", "review.failed") for e in events):
                break

            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())


@app.get("/api/reviews/{run_id}/report")
async def get_report(run_id: str):
    """获取审查报告（JSON 和 Markdown）。"""
    store = _get_store()
    run_dir = Path(_config.runs_dir if _config else "runs") / run_id

    result_file = run_dir / "result.json"
    report_file = run_dir / "report.md"

    if not result_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"报告不存在: {run_id}",
        )

    return {
        "json": json.loads(result_file.read_text(encoding="utf-8")),
        "markdown": report_file.read_text(encoding="utf-8") if report_file.exists() else "",
    }


@app.get("/api/runs")
async def list_runs():
    """列出历史运行。"""
    store = _get_store()
    runs = store.list_runs()
    return {"runs": runs, "count": len(runs)}


@app.get("/api/replays/{run_id}/events")
async def replay_run_events(run_id: str, speed: float = 1.0):
    """回放历史运行的事件流（支持变速）。

    Args:
        run_id: 运行 ID
        speed: 回放速度倍率（1.0=原速, 2.0=两倍速）
    """
    store = _get_store()
    events = store.read(run_id)

    if not events:
        raise HTTPException(
            status_code=404,
            detail=f"Replay 运行不存在: {run_id}",
        )

    async def replay_generator() -> AsyncIterator[dict]:
        for event in replay_events(events, speed):
            yield {
                "event": event.type,
                "data": event.model_dump_json(),
            }
            await asyncio.sleep(0.05 / speed)  # 最小间隔

    return EventSourceResponse(replay_generator())


@app.get("/api/benchmarks/latest")
async def get_latest_benchmark():
    """获取最近一次评测摘要。"""
    # TODO: 实现 Benchmark 摘要查询
    return {"message": "评测功能开发中"}
