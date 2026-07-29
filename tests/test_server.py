"""验证 FastAPI 审查服务、SSE 与历史回放的公开契约。"""

from __future__ import annotations

import asyncio
import json
import math
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reviewcrew.config import Config
from reviewcrew.events import EventStore, PipelineEvent
from reviewcrew.schemas import ReviewRequest, ReviewResult
from reviewcrew.server.app import create_app
from reviewcrew.server.replay import replay_events


def _result(run_id: str, *, status: str = "completed") -> ReviewResult:
    now = datetime(2026, 7, 30, 1, 2, 3, tzinfo=UTC)
    return ReviewResult(
        run_id=run_id,
        status=status,
        repository="owner/repo",
        base_sha="base",
        head_sha="head",
        findings=[],
        rejected_count=0,
        coverage=["src/app.py"],
        warnings=[],
        started_at=now,
        completed_at=now + timedelta(seconds=1),
        elapsed_seconds=1.0,
    )


def _event(
    sequence: int,
    timestamp: datetime,
    event_type: str,
    *,
    run_id: str = "run-replay",
    data: dict[str, Any] | None = None,
) -> PipelineEvent:
    return PipelineEvent(
        id=f"evt-{sequence}",
        run_id=run_id,
        sequence=sequence,
        timestamp=timestamp,
        type=event_type,
        data=data or {},
    )


class _BlockingOrchestrator:
    """保持审查运行，供状态接口验证不伪造结果。"""

    def __init__(self) -> None:
        self.started = False
        self.cancelled = False

    async def review(self, request: ReviewRequest, *, run_id: str) -> ReviewResult:
        self.started = True
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled = True
        raise AssertionError("不可到达")


class _FailingOrchestrator:
    async def review(self, request: ReviewRequest, *, run_id: str) -> ReviewResult:
        raise RuntimeError("secret upstream response")


class _SuccessfulOrchestrator:
    async def review(self, request: ReviewRequest, *, run_id: str) -> ReviewResult:
        return _result(run_id)


class _KeywordOrchestrator:
    async def review(self, request: ReviewRequest, **kwargs: Any) -> ReviewResult:
        assert kwargs["emit_terminal_event"] is False
        return _result(kwargs["run_id"])


class _PrematureTerminalOrchestrator:
    def __init__(self, store: EventStore) -> None:
        self.store = store

    async def review(
        self,
        request: ReviewRequest,
        *,
        run_id: str,
        emit_terminal_event: bool = True,
    ) -> ReviewResult:
        if emit_terminal_event:
            self.store.emit(run_id, "review.completed", {"status": "completed"})
        raise RuntimeError("完成事件之后仍然失败")


class _OverlapEventStore(EventStore):
    """让首条实时事件与历史重叠，再产生终态事件。"""

    async def subscribe(self, run_id: str):  # type: ignore[no-untyped-def]
        yield self.read(run_id)[0]
        yield self.emit(run_id, "review.completed", {"status": "completed"})


def _parse_sse(response_text: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for block in response_text.strip().split("\n\n"):
        lines = [line for line in block.splitlines() if line.startswith("data: ")]
        if lines:
            payloads.append(json.loads(lines[0][len("data: ") :]))
    return payloads


def test_post_review_returns_202_and_running_status_without_fake_result(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "runs")
    orchestrator = _BlockingOrchestrator()
    app = create_app(
        config=Config(runs_dir=store.root),
        event_store=store,
        orchestrator=orchestrator,
    )

    with TestClient(app) as client:
        response = client.post("/api/reviews", json={"pr_url": "https://github.com/o/r/pull/1"})
        assert response.status_code == 202
        body = response.json()
        assert body == {"run_id": body["run_id"], "status": "running"}

        status = client.get(f"/api/reviews/{body['run_id']}")
        assert status.status_code == 200
        assert status.json() == {"run_id": body["run_id"], "status": "running"}
        assert orchestrator.started is True


def test_background_exception_emits_failed_terminal_event(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "runs")
    app = create_app(
        config=Config(runs_dir=store.root),
        event_store=store,
        orchestrator=_FailingOrchestrator(),
    )

    with TestClient(app) as client:
        response = client.post("/api/reviews", json={"pr_url": "https://github.com/o/r/pull/1"})
        run_id = response.json()["run_id"]
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            events = store.read(run_id)
            if events and events[-1].type == "review.failed":
                break
            time.sleep(0.01)

        assert [event.type for event in store.read(run_id)] == ["review.failed"]
        status = client.get(f"/api/reviews/{run_id}")
        assert status.json() == {"run_id": run_id, "status": "failed"}
        assert "secret upstream response" not in json.dumps(status.json(), ensure_ascii=False)
        failed_stream = client.get(f"/api/reviews/{run_id}/events")
        assert [item["type"] for item in _parse_sse(failed_stream.text)] == ["review.failed"]


def test_background_exception_overrides_premature_completed_event(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "runs")
    app = create_app(
        config=Config(runs_dir=store.root),
        event_store=store,
        orchestrator=_PrematureTerminalOrchestrator(store),
    )

    with TestClient(app) as client:
        run_id = client.post(
            "/api/reviews", json={"pr_url": "https://github.com/o/r/pull/1"}
        ).json()["run_id"]
        status = client.get(f"/api/reviews/{run_id}")
        stream = client.get(f"/api/reviews/{run_id}/events")

    assert status.json() == {"run_id": run_id, "status": "failed"}
    assert [item["type"] for item in _parse_sse(stream.text)] == ["review.failed"]
    assert [event.type for event in store.read(run_id)] == ["review.failed"]
    assert store.read(run_id)[-1].type == "review.failed"


def test_api_uses_chinese_details_for_missing_and_invalid_requests(tmp_path: Path) -> None:
    app = create_app(config=Config(runs_dir=tmp_path / "runs"))

    with TestClient(app) as client:
        missing = client.get("/api/reviews/not-found")
        invalid = client.post("/api/reviews", json={})

    assert missing.status_code == 404
    assert "未找到" in missing.json()["detail"]
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "审查请求参数无效，请检查后重试。"}


def test_injected_fake_result_is_available_to_status_and_report_without_disk_write(
    tmp_path: Path,
) -> None:
    store = EventStore(tmp_path / "runs")
    app = create_app(
        config=Config(runs_dir=store.root),
        event_store=store,
        orchestrator=_SuccessfulOrchestrator(),
    )

    with TestClient(app) as client:
        started = client.post(
            "/api/reviews", json={"pr_url": "https://github.com/o/r/pull/1"}
        ).json()
        run_id = started["run_id"]
        status = client.get(f"/api/reviews/{run_id}")
        json_report = client.get(f"/api/reviews/{run_id}/report?format=json")
        markdown_report = client.get(f"/api/reviews/{run_id}/report?format=markdown")

    assert status.json()["status"] == "completed"
    assert json_report.json()["run_id"] == run_id
    assert "# ReviewCrew 审查报告" in markdown_report.text


def test_injected_fake_can_accept_server_arguments_via_keyword_parameters(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "runs")
    app = create_app(
        config=Config(runs_dir=store.root),
        event_store=store,
        orchestrator=_KeywordOrchestrator(),
    )

    with TestClient(app) as client:
        run_id = client.post(
            "/api/reviews", json={"pr_url": "https://github.com/o/r/pull/1"}
        ).json()["run_id"]
        status = client.get(f"/api/reviews/{run_id}")

    assert status.json()["status"] == "completed"


def test_sse_replays_persisted_events_deduplicates_overlap_and_closes(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "runs")
    run_id = store.create_run()
    store.emit(run_id, "review.started", {"prompt": "hidden", "stage": "loading"})
    store.emit(run_id, "review.completed", {"status": "completed"})
    app = create_app(config=Config(runs_dir=store.root), event_store=store)

    with TestClient(app) as client:
        response = client.get(f"/api/reviews/{run_id}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    payloads = _parse_sse(response.text)
    assert [payload["sequence"] for payload in payloads] == [1, 2]
    assert [payload["type"] for payload in payloads] == ["review.started", "review.completed"]
    assert payloads[0]["data"] == {"stage": "loading"}
    assert set(payloads[0]) == {"id", "run_id", "sequence", "timestamp", "type", "data"}


def test_sse_backfills_history_then_follows_live_events_without_duplicate(tmp_path: Path) -> None:
    store = _OverlapEventStore(tmp_path / "runs")
    run_id = store.create_run()
    store.emit(run_id, "review.started", {"mode": "github"})
    app = create_app(config=Config(runs_dir=store.root), event_store=store)

    with TestClient(app) as client:
        response = client.get(f"/api/reviews/{run_id}/events")

    payloads = _parse_sse(response.text)
    assert [(item["sequence"], item["type"]) for item in payloads] == [
        (1, "review.started"),
        (2, "review.completed"),
    ]


def test_report_runs_and_latest_benchmark_are_read_from_safe_fixed_directories(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    store = EventStore(runs_dir)
    run_id = store.create_run()
    store.emit(run_id, "review.completed", {"status": "completed"})
    result = _result(run_id)
    run_dir = runs_dir / run_id
    (run_dir / "result.json").write_text(result.model_dump_json(), encoding="utf-8")
    (run_dir / "report.md").write_text("# 已脱敏报告\n", encoding="utf-8")
    benchmark_dir = tmp_path / "benchmark" / "results"
    benchmark_run_dir = benchmark_dir / "20260730-090000"
    benchmark_run_dir.mkdir(parents=True)
    (benchmark_run_dir / "summary.json").write_text(
        json.dumps({"executed": 5, "prompt": "hidden"}, ensure_ascii=False),
        encoding="utf-8",
    )
    app = create_app(
        config=Config(runs_dir=runs_dir),
        event_store=store,
        benchmark_results_dir=benchmark_dir,
    )

    with TestClient(app) as client:
        status = client.get(f"/api/reviews/{run_id}")
        json_report = client.get(f"/api/reviews/{run_id}/report?format=json")
        markdown_report = client.get(f"/api/reviews/{run_id}/report?format=markdown")
        runs = client.get("/api/runs")
        benchmark = client.get("/api/benchmarks/latest")
        traversal = client.get("/api/reviews/..%5Coutside/report")

    assert status.json()["status"] == "completed"
    assert json_report.json()["run_id"] == run_id
    assert markdown_report.text == "# 已脱敏报告\n"
    assert runs.json()["runs"][0]["run_id"] == run_id
    assert benchmark.json() == {"executed": 5}
    assert traversal.status_code == 404
    assert "未找到" in traversal.json()["detail"]


def test_absent_report_and_benchmark_return_chinese_404(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "runs")
    run_id = store.create_run()
    app = create_app(
        config=Config(runs_dir=store.root),
        event_store=store,
        benchmark_results_dir=tmp_path / "benchmark" / "results",
    )

    with TestClient(app) as client:
        report = client.get(f"/api/reviews/{run_id}/report")
        benchmark = client.get("/api/benchmarks/latest")

    assert report.status_code == 404
    assert "报告" in report.json()["detail"]
    assert benchmark.status_code == 404
    assert "评测" in benchmark.json()["detail"]


@pytest.mark.skipif(os.name != "nt", reason="NTFS Junction 是 Windows 专项边界")
def test_run_and_benchmark_junctions_cannot_escape_fixed_roots(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    outside_run = tmp_path / "outside-run"
    outside_run.mkdir()
    (outside_run / "report.md").write_text("外部秘密", encoding="utf-8")
    run_junction = runs_dir / "run-junction"

    benchmark_dir = tmp_path / "benchmark" / "results"
    benchmark_dir.mkdir(parents=True)
    outside_benchmark = tmp_path / "outside-benchmark"
    outside_benchmark.mkdir()
    (outside_benchmark / "summary.json").write_text('{"secret": true}', encoding="utf-8")
    benchmark_junction = benchmark_dir / "20260730-090000"

    for junction, target in (
        (run_junction, outside_run),
        (benchmark_junction, outside_benchmark),
    ):
        created = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode != 0:
            pytest.skip("当前环境不允许创建 NTFS Junction")

    app = create_app(
        config=Config(runs_dir=runs_dir),
        event_store=EventStore(runs_dir),
        benchmark_results_dir=benchmark_dir,
    )
    try:
        with TestClient(app) as client:
            report = client.get("/api/reviews/run-junction/report?format=markdown")
            benchmark = client.get("/api/benchmarks/latest")
    finally:
        run_junction.rmdir()
        benchmark_junction.rmdir()

    assert report.status_code == 404
    assert benchmark.status_code == 404


def test_broken_markdown_report_returns_chinese_json_error(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "runs")
    run_id = store.create_run()
    (store.root / run_id / "report.md").write_bytes(b"\xff\xfe")
    app = create_app(config=Config(runs_dir=store.root), event_store=store)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/api/reviews/{run_id}/report?format=markdown")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "审查报告文件损坏，暂时无法读取。"}


@pytest.mark.parametrize(
    "path",
    [
        "/api/reviews/{run_id}",
        "/api/reviews/{run_id}/events",
        "/api/replays/{run_id}/events",
        "/api/runs",
    ],
)
def test_broken_event_file_returns_chinese_json_error(tmp_path: Path, path: str) -> None:
    store = EventStore(tmp_path / "runs")
    run_id = store.create_run()
    (store.root / run_id / "events.jsonl").write_text("{broken\n", encoding="utf-8")
    app = create_app(config=Config(runs_dir=store.root), event_store=store)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(path.format(run_id=run_id))

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "审查事件文件损坏，暂时无法读取。"}


def test_runs_endpoint_returns_bounded_summaries_without_parsing_result_files(
    tmp_path: Path,
) -> None:
    store = EventStore(tmp_path / "runs")
    older = store.create_run()
    store.emit(older, "review.completed", {"status": "partial"})
    (store.root / older / "result.json").write_text("{broken", encoding="utf-8")
    newer = store.create_run()
    store.emit(newer, "review.failed", {"status": "failed"})
    (store.root / newer / "result.json").write_text("{also-broken", encoding="utf-8")
    app = create_app(config=Config(runs_dir=store.root), event_store=store)

    with TestClient(app) as client:
        response = client.get("/api/runs?limit=1&offset=0")

    assert response.status_code == 200
    assert response.json() == {
        "runs": [{"run_id": newer, "status": "failed"}],
        "total": 2,
        "limit": 1,
        "offset": 0,
    }


@pytest.mark.asyncio
async def test_replay_sorts_stably_and_scales_delays_with_injected_sleep() -> None:
    start = datetime(2026, 7, 30, tzinfo=UTC)
    events = [
        _event(3, start + timedelta(seconds=6), "review.completed"),
        _event(2, start + timedelta(seconds=2), "stage.started"),
        _event(1, start + timedelta(seconds=2), "review.started"),
    ]
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    replayed = [event async for event in replay_events(events, speed=2, sleep=fake_sleep)]

    assert [event.sequence for event in replayed] == [1, 2, 3]
    assert sleeps == [0.0, 2.0]


@pytest.mark.parametrize("speed", [0, -1, math.inf, -math.inf, math.nan])
@pytest.mark.asyncio
async def test_replay_rejects_non_positive_or_non_finite_speed(speed: float) -> None:
    with pytest.raises(ValueError, match="回放速度"):
        _ = [event async for event in replay_events([], speed=speed)]


def test_replay_endpoint_uses_pipeline_event_sse_and_rejects_infinite_speed(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "runs")
    run_id = store.create_run()
    store.emit(run_id, "review.started", {})
    store.emit(run_id, "review.completed", {"status": "completed"})
    app = create_app(config=Config(runs_dir=store.root), event_store=store)

    with TestClient(app) as client:
        replay = client.get(f"/api/replays/{run_id}/events?speed=1000000")
        invalid = client.get(f"/api/replays/{run_id}/events?speed=inf")

    assert [item["type"] for item in _parse_sse(replay.text)] == [
        "review.started",
        "review.completed",
    ]
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "回放速度必须是大于零的有限数值。"}
