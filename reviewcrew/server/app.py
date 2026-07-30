from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from reviewcrew.events import EventLogger
from reviewcrew.models import PipelineEvent, WorkflowNode
from reviewcrew.pipeline.orchestrator import Orchestrator
from reviewcrew.server.replay import (
    encode_sse,
    load_events_jsonl,
    replay_events,
    tail_events_file,
)
from reviewcrew.server.repository import prepare_repository

RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class ReviewRequest(BaseModel):
    pr_url: str = Field(min_length=1)
    repo_path: str | None = None


def create_app(
    runs_dir: Path = Path("runs"),
    benchmark_results_dir: Path = Path("benchmark/results"),
    repos_dir: Path = Path("repos"),
) -> FastAPI:
    application = FastAPI(title="ReviewCrew API", version="0.1.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^http://(?:localhost|127\.0\.0\.1):\d+$",
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.state.runs_dir = runs_dir
    application.state.tasks = set()
    application.state.active_run_ids = set()

    def run_path(run_id: str) -> Path:
        if not RUN_ID.fullmatch(run_id):
            raise HTTPException(status_code=400, detail="Invalid run ID")
        return runs_dir / run_id

    def record_run_error(run_id: str, error: Exception | str) -> None:
        target = run_path(run_id)
        target.mkdir(parents=True, exist_ok=True)
        if target.joinpath("error.json").exists():
            return
        error_name = type(error).__name__ if isinstance(error, Exception) else "Interrupted"
        error_message = str(error)
        message = f"{error_name}: {error_message}"
        target.joinpath("error.json").write_text(
            json.dumps({"error": error_name, "message": error_message}),
            encoding="utf-8",
        )
        logger = EventLogger(run_id, runs_dir)
        logger.emit(
            PipelineEvent(
                timestamp=time.time(),
                type="workflow_node",
                workflow_node=WorkflowNode(
                    id="input",
                    kind="input",
                    label="审查输入",
                    status="failed",
                    detail=message,
                ),
            )
        )
        logger.emit(
            PipelineEvent(
                timestamp=time.time(),
                type="stage",
                stage="context",
                status="error",
                text=message,
            )
        )

    @application.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/api/review", status_code=202)
    async def start_review(request: ReviewRequest) -> dict[str, str]:
        run_id = uuid.uuid4().hex[:12]

        async def execute() -> None:
            try:
                repo = await asyncio.to_thread(
                    prepare_repository,
                    request.pr_url,
                    request.repo_path,
                    repos_dir,
                )
                await Orchestrator(runs_dir=runs_dir).review(request.pr_url, repo, run_id=run_id)
            except Exception as error:
                record_run_error(run_id, error)

        application.state.active_run_ids.add(run_id)
        task = asyncio.create_task(execute())
        application.state.tasks.add(task)

        def finish(completed: asyncio.Task[None]) -> None:
            application.state.tasks.discard(completed)
            application.state.active_run_ids.discard(run_id)

        task.add_done_callback(finish)
        return {"run_id": run_id}

    @application.get("/api/stream/{run_id}")
    async def stream(run_id: str) -> StreamingResponse:
        path = run_path(run_id) / "events.jsonl"

        async def generate() -> AsyncIterator[str]:
            async for event in tail_events_file(path):
                yield encode_sse(event)

        return StreamingResponse(generate(), media_type="text/event-stream")

    @application.get("/api/replay/{run_id}")
    async def replay(
        run_id: str, speed: float = Query(default=1.0, gt=0, le=100)
    ) -> StreamingResponse:
        path = run_path(run_id) / "events.jsonl"
        try:
            events = load_events_jsonl(path)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error

        async def generate() -> AsyncIterator[str]:
            async for event in replay_events(events, speed):
                yield encode_sse(event)

        return StreamingResponse(generate(), media_type="text/event-stream")

    @application.get("/api/runs")
    async def runs() -> list[dict[str, object]]:
        if not runs_dir.exists():
            return []
        output: list[dict[str, object]] = []
        for directory in sorted(runs_dir.iterdir(), reverse=True):
            if not directory.is_dir():
                continue
            events_path = directory / "events.jsonl"
            events = load_events_jsonl(events_path) if events_path.exists() else []
            output.append(
                {
                    "run_id": directory.name,
                    "status": (
                        "done"
                        if any(event.type == "report" for event in events)
                        else "failed"
                        if (directory / "error.json").exists()
                        else "running"
                    ),
                    "event_count": len(events),
                    "has_error": (directory / "error.json").exists(),
                }
            )
        return output

    @application.get("/api/runs/{run_id}")
    async def run_detail(run_id: str) -> dict[str, object]:
        directory = run_path(run_id)
        if not directory.is_dir():
            raise HTTPException(status_code=404, detail="Run not found")
        events_path = directory / "events.jsonl"
        events = load_events_jsonl(events_path) if events_path.exists() else []
        if (
            events
            and not any(event.type == "report" for event in events)
            and not (directory / "error.json").exists()
            and run_id not in application.state.active_run_ids
        ):
            record_run_error(run_id, "服务已重启或后台任务意外中断，请重新提交审查。")
            events = load_events_jsonl(events_path)
        report_path = directory / "report.md"
        diff_path = directory / "change.diff"
        return {
            "run_id": run_id,
            "events": [event.model_dump(exclude_none=True) for event in events],
            "report": report_path.read_text(encoding="utf-8") if report_path.exists() else None,
            "diff": diff_path.read_text(encoding="utf-8") if diff_path.exists() else None,
        }

    @application.get("/api/benchmark/latest")
    async def benchmark_latest() -> dict[str, object]:
        summaries = sorted(benchmark_results_dir.glob("*/summary.md"), reverse=True)
        for summary in summaries:
            results_path = summary.parent / "results.jsonl"
            rows = (
                [json.loads(line) for line in results_path.read_text().splitlines() if line]
                if results_path.exists()
                else []
            )
            if rows:
                return {
                    "available": True,
                    "summary": summary.read_text(encoding="utf-8"),
                    "results": rows,
                }
        return {"available": False, "summary": None, "results": []}

    return application


app = create_app()
