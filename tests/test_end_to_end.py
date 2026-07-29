"""端到端集成测试 —— Fake 模式完整链路和 CLI 命令验证。

所有测试不依赖网络，使用 Fake Model 和本地 git 仓库。
"""

import subprocess
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _create_test_repo(repo_dir: Path) -> None:
    """在指定目录创建最小 git 仓库（含一个 Python 文件）。"""
    repo_dir.mkdir(parents=True, exist_ok=True)
    env = {
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@test.com",
    }
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
    (repo_dir / "main.py").write_text("print('hello')\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo_dir,
        capture_output=True,
        check=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# Fake 完整管道测试
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fake_full_pipeline(tmp_path: Path):
    """Fake 模式完整链路：创建仓库 → 审查 → 验证报告与事件持久化。"""
    from reviewcrew.config import Config
    from reviewcrew.events import EventStore
    from reviewcrew.pipeline.orchestrator import Orchestrator
    from reviewcrew.schemas import ReviewRequest
    from reviewcrew.llm.glm import build_fake_model

    # 创建临时仓库
    repo_dir = tmp_path / "repo"
    _create_test_repo(repo_dir)

    # 配置
    config = Config.from_env()
    config.runs_dir = str(tmp_path / "runs")
    store = EventStore(config.runs_dir)
    orch = Orchestrator(config, store)
    orch.model = build_fake_model()

    # 执行审查
    result = await orch.review(
        ReviewRequest(
            repo_path=str(repo_dir),
            base_ref="HEAD",
            head_ref="HEAD",
        )
    )

    # 验证结果结构
    assert result.run_id is not None
    assert result.status in ("completed", "partial")

    # 验证持久化文件
    result_file = Path(config.runs_dir) / result.run_id / "result.json"
    assert result_file.exists(), f"result.json 应存在: {result_file}"

    report_file = Path(config.runs_dir) / result.run_id / "report.md"
    assert report_file.exists(), f"report.md 应存在: {report_file}"

    # 验证事件
    events = store.read(result.run_id)
    assert len(events) >= 3, f"预期至少 3 条事件（started + stage + completed），实际: {len(events)}"

    # 验证事件类型
    event_types = [e.type for e in events]
    assert "review.started" in event_types
    assert "review.completed" in event_types


@pytest.mark.asyncio
async def test_fake_full_pipeline_result_json_content(tmp_path: Path):
    """result.json 内容应包含 run_id、status、findings 等关键字段。"""
    import json
    from reviewcrew.config import Config
    from reviewcrew.events import EventStore
    from reviewcrew.pipeline.orchestrator import Orchestrator
    from reviewcrew.schemas import ReviewRequest
    from reviewcrew.llm.glm import build_fake_model

    repo_dir = tmp_path / "repo"
    _create_test_repo(repo_dir)

    config = Config.from_env()
    config.runs_dir = str(tmp_path / "runs")
    store = EventStore(config.runs_dir)
    orch = Orchestrator(config, store)
    orch.model = build_fake_model()

    result = await orch.review(
        ReviewRequest(repo_path=str(repo_dir), base_ref="HEAD", head_ref="HEAD")
    )

    result_file = Path(config.runs_dir) / result.run_id / "result.json"
    content = json.loads(result_file.read_text(encoding="utf-8"))

    assert content["run_id"] == result.run_id
    assert "status" in content
    assert "findings" in content
    assert isinstance(content["findings"], list)
    assert "elapsed_seconds" in content


@pytest.mark.asyncio
async def test_fake_full_pipeline_report_md_content(tmp_path: Path):
    """report.md 应包含仓库信息和 Finding 数量。"""
    from reviewcrew.config import Config
    from reviewcrew.events import EventStore
    from reviewcrew.pipeline.orchestrator import Orchestrator
    from reviewcrew.schemas import ReviewRequest
    from reviewcrew.llm.glm import build_fake_model

    repo_dir = tmp_path / "repo"
    _create_test_repo(repo_dir)

    config = Config.from_env()
    config.runs_dir = str(tmp_path / "runs")
    store = EventStore(config.runs_dir)
    orch = Orchestrator(config, store)
    orch.model = build_fake_model()

    result = await orch.review(
        ReviewRequest(repo_path=str(repo_dir), base_ref="HEAD", head_ref="HEAD")
    )

    report_file = Path(config.runs_dir) / result.run_id / "report.md"
    content = report_file.read_text(encoding="utf-8")

    # 报告应包含 Finding 数量信息
    assert str(len(result.findings)) in content or "发现" in content


@pytest.mark.asyncio
async def test_fake_full_pipeline_events_are_valid_jsonl(tmp_path: Path):
    """events.jsonl 每行应为有效 JSON 且包含 PipelineEvent 必需字段。"""
    import json
    from reviewcrew.config import Config
    from reviewcrew.events import EventStore
    from reviewcrew.pipeline.orchestrator import Orchestrator
    from reviewcrew.schemas import ReviewRequest
    from reviewcrew.llm.glm import build_fake_model

    repo_dir = tmp_path / "repo"
    _create_test_repo(repo_dir)

    config = Config.from_env()
    config.runs_dir = str(tmp_path / "runs")
    store = EventStore(config.runs_dir)
    orch = Orchestrator(config, store)
    orch.model = build_fake_model()

    result = await orch.review(
        ReviewRequest(repo_path=str(repo_dir), base_ref="HEAD", head_ref="HEAD")
    )

    events_file = Path(config.runs_dir) / result.run_id / "events.jsonl"
    assert events_file.exists()

    lines = events_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) >= 3

    for i, line in enumerate(lines):
        data = json.loads(line)
        assert "id" in data, f"第 {i} 行缺少 id"
        assert "run_id" in data, f"第 {i} 行缺少 run_id"
        assert "sequence" in data, f"第 {i} 行缺少 sequence"
        assert "type" in data, f"第 {i} 行缺少 type"
        assert "timestamp" in data, f"第 {i} 行缺少 timestamp"

    # 验证序列号连续递增
    sequences = [json.loads(line)["sequence"] for line in lines]
    assert sequences == sorted(sequences)
    assert sequences[0] == 1


# ---------------------------------------------------------------------------
# CLI 命令测试
# ---------------------------------------------------------------------------

def test_cli_review_command_local_repo(tmp_path: Path):
    """CLI review 命令应在本地仓库模式下正常执行（通过 Python 子进程）。"""
    import sys

    repo_dir = tmp_path / "repo"
    _create_test_repo(repo_dir)

    result = subprocess.run(
        [
            sys.executable, "-m", "reviewcrew.cli", "review",
            "--repo", str(repo_dir),
            "--base", "HEAD",
            "--head", "HEAD",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env={**__import__("os").environ, "REVIEWCREW_RUNS_DIR": str(tmp_path / "runs")},
    )

    # CLI 应成功退出
    assert result.returncode == 0, f"CLI 退出码异常: {result.returncode}\nstderr: {result.stderr}"
    assert "审查完成" in result.stderr or "审查完成" in result.stdout or "completed" in result.stderr.lower()


def test_cli_review_command_creates_run_dir(tmp_path: Path):
    """CLI review 应在 runs_dir 下创建运行目录。"""
    import sys

    repo_dir = tmp_path / "repo"
    _create_test_repo(repo_dir)

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True)

    subprocess.run(
        [
            sys.executable, "-m", "reviewcrew.cli", "review",
            "--repo", str(repo_dir),
            "--base", "HEAD",
            "--head", "HEAD",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env={**__import__("os").environ, "REVIEWCREW_RUNS_DIR": str(runs_dir)},
    )

    # 应创建至少一个运行目录
    run_dirs = list(runs_dir.iterdir())
    assert len(run_dirs) >= 1, f"runs_dir 中应至少有一个目录，实际: {list(runs_dir.iterdir())}"

    # 运行目录应包含 result.json 和 events.jsonl
    run_dir = run_dirs[0]
    assert (run_dir / "result.json").exists()
    assert (run_dir / "events.jsonl").exists()


def test_cli_review_no_args_shows_error(tmp_path: Path):
    """无参数调用 review 命令应报错（缺少模式参数）。"""
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "reviewcrew.cli"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    # 缺少子命令应返回非零退出码
    assert result.returncode != 0
