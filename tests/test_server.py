from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reviewcrew.models import PipelineEvent
from reviewcrew.server.app import create_app


def write_run(runs_dir: Path, run_id: str = "test123") -> None:
    directory = runs_dir / run_id
    directory.mkdir(parents=True)
    events = [
        PipelineEvent(timestamp=1, type="stage", stage="preprocess", status="start"),
        PipelineEvent(timestamp=3, type="stage", stage="preprocess", status="done"),
        PipelineEvent(timestamp=4, type="report", markdown="# Done"),
    ]
    directory.joinpath("events.jsonl").write_text(
        "\n".join(event.model_dump_json() for event in events) + "\n", encoding="utf-8"
    )
    directory.joinpath("report.md").write_text("# Done\n", encoding="utf-8")


def test_health_and_request_validation(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    assert client.get("/api/health").json() == {"status": "ok"}
    response = client.post("/api/review", json={})
    assert response.status_code == 422


def test_local_frontend_port_is_allowed_by_cors(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://127.0.0.1:5175",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5175"


def test_review_accepts_missing_repository_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = tmp_path / "repos" / "owner__repo"
    prepared.mkdir(parents=True)
    preparation_calls: list[tuple[str, str | None, Path]] = []
    preparation_started = threading.Event()
    release_preparation = threading.Event()
    reviewed = threading.Event()

    def prepare(pr_url: str, repo_path: str | None, repos_dir: Path) -> Path:
        preparation_calls.append((pr_url, repo_path, repos_dir))
        preparation_started.set()
        assert release_preparation.wait(timeout=1)
        return prepared

    async def review(
        _self: object,
        _pr_url: str,
        repo_path: Path,
        run_id: str | None = None,
    ) -> object:
        assert repo_path == prepared
        assert run_id is not None
        reviewed.set()
        return object()

    monkeypatch.setattr("reviewcrew.server.app.prepare_repository", prepare)
    monkeypatch.setattr("reviewcrew.server.app.Orchestrator.review", review)
    repos_dir = tmp_path / "repos"

    with TestClient(create_app(tmp_path / "runs", repos_dir=repos_dir)) as client:
        response = client.post(
            "/api/review",
            json={"pr_url": "https://github.com/owner/repo/pull/42"},
        )
        assert response.status_code == 202
        assert preparation_started.wait(timeout=1)
        run_id = response.json()["run_id"]
        detail = client.get(f"/api/runs/{run_id}")
        assert detail.status_code == 200
        assert detail.json()["events"][0]["workflow_node"]["detail"] == (
            "首次使用会自动克隆，已有缓存将执行快速更新。"
        )
        release_preparation.set()
        assert reviewed.wait(timeout=1)

    assert preparation_calls == [
        ("https://github.com/owner/repo/pull/42", None, repos_dir)
    ]


def test_replay_is_sse_and_run_detail(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    write_run(runs_dir)
    client = TestClient(create_app(runs_dir))
    response = client.get("/api/replay/test123?speed=100")
    assert response.status_code == 200
    assert "event: stage" in response.text
    assert "data:" in response.text
    detail = client.get("/api/runs/test123").json()
    assert detail["report"] == "# Done\n"
    assert len(detail["events"]) == 3


def test_runs_lists_completed_run(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    write_run(runs_dir)
    client = TestClient(create_app(runs_dir))
    [run] = client.get("/api/runs").json()
    assert run == {
        "run_id": "test123",
        "status": "done",
        "event_count": 3,
        "has_error": False,
    }


def test_runs_lists_failed_run_as_failed(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    directory = runs_dir / "failed123"
    directory.mkdir(parents=True)
    event = PipelineEvent(
        timestamp=1,
        type="stage",
        stage="context",
        status="error",
        text="context failed",
    )
    directory.joinpath("events.jsonl").write_text(
        event.model_dump_json() + "\n", encoding="utf-8"
    )
    directory.joinpath("error.json").write_text("{}", encoding="utf-8")

    [run] = TestClient(create_app(runs_dir)).get("/api/runs").json()

    assert run["status"] == "failed"
    assert run["has_error"] is True


def test_run_detail_marks_orphaned_run_as_interrupted(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    directory = runs_dir / "orphaned123"
    directory.mkdir(parents=True)
    event = PipelineEvent(
        timestamp=1,
        type="workflow_node",
        workflow_node={
            "id": "input",
            "kind": "input",
            "label": "审查输入",
            "status": "running",
        },
    )
    directory.joinpath("events.jsonl").write_text(
        event.model_dump_json() + "\n", encoding="utf-8"
    )

    detail = TestClient(create_app(runs_dir)).get("/api/runs/orphaned123").json()

    assert detail["events"][-1]["type"] == "stage"
    assert detail["events"][-1]["status"] == "error"
    assert directory.joinpath("error.json").exists()


def test_event_json_remains_frontend_contract(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    write_run(runs_dir)
    payload = json.loads((runs_dir / "test123" / "events.jsonl").read_text().splitlines()[0])
    assert payload["type"] == "stage"
    assert payload["stage"] == "preprocess"


def test_empty_benchmark_result_is_not_reported_as_available(tmp_path: Path) -> None:
    result_dir = tmp_path / "benchmark" / "20260729T000000Z"
    result_dir.mkdir(parents=True)
    result_dir.joinpath("results.jsonl").write_text("", encoding="utf-8")
    result_dir.joinpath("summary.md").write_text("# Empty\n", encoding="utf-8")
    client = TestClient(create_app(tmp_path / "runs", tmp_path / "benchmark"))

    assert client.get("/api/benchmark/latest").json() == {
        "available": False,
        "summary": None,
        "results": [],
    }
