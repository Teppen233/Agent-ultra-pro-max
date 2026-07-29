"""FastAPI 服务与 CLI 测试。"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient


# ---- Server ----

@pytest.fixture
def client(tmp_path: Path):
    """创建测试用 FastAPI TestClient。"""
    from reviewcrew.config import Config
    from reviewcrew.server.app import app, init_app

    config = Config.from_env()
    config.runs_dir = str(tmp_path / "runs")
    init_app(config)

    return TestClient(app)


def test_api_health(client):
    """GET /api/runs 应返回运行列表。"""
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data


def test_api_review_status_404(client):
    """不存在的 run_id 应返回 404 和中文错误。"""
    resp = client.get("/api/reviews/nonexistent")
    assert resp.status_code == 404
    data = resp.json()
    assert "detail" in data


def test_api_start_review_fake(client):
    """POST /api/reviews 应正常启动（Fake 模式）。"""
    resp = client.post("/api/reviews", json={
        "pr_url": "https://github.com/test/demo/pull/1"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data


def test_api_report_404(client):
    """无报告的 run 应返回 404。"""
    resp = client.get("/api/reviews/nonexistent/report")
    assert resp.status_code == 404


def test_api_replay_404(client):
    """不存在的 replay 应返回 404。"""
    resp = client.get("/api/replays/nonexistent/events")
    assert resp.status_code == 404
