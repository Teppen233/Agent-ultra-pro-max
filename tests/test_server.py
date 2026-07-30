from __future__ import annotations

import json
import subprocess
from pathlib import Path

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


def test_health_and_start_validation(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    assert client.get("/api/health").json() == {"status": "ok"}
    response = client.post(
        "/api/review", json={"pr_url": "https://example.test/pr/1", "repo_path": "missing"}
    )
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


def test_review_rejects_pr_from_different_github_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "remote",
            "add",
            "origin",
            "https://github.com/Netflix/metaflow.git",
        ],
        check=True,
        capture_output=True,
    )
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post(
        "/api/review",
        json={
            "pr_url": "https://github.com/keycloak/keycloak/pull/1",
            "repo_path": str(repo),
        },
    )

    assert response.status_code == 422
    assert "PR 属于 keycloak/keycloak" in response.json()["detail"]


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
