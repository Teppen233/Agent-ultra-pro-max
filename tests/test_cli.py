"""ReviewCrew 命令行入口测试。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from reviewcrew.cli import main
from reviewcrew.config import Config
from reviewcrew.schemas import ReviewRequest, ReviewResult


def make_result(*, status: str = "completed", run_id: str = "run-cli") -> ReviewResult:
    """构造 CLI 可展示的结果。"""

    timestamp = datetime(2026, 7, 29, tzinfo=UTC)
    return ReviewResult(
        run_id=run_id,
        status=status,
        repository="acme/demo",
        base_sha="base",
        head_sha="head",
        started_at=timestamp,
        completed_at=timestamp,
        elapsed_seconds=0.1,
    )


class FakeOrchestrator:
    """记录请求并返回固定审查结果。"""

    def __init__(self, result: ReviewResult) -> None:
        self.result = result
        self.requests: list[ReviewRequest] = []

    async def review(self, request: ReviewRequest) -> ReviewResult:
        self.requests.append(request)
        return self.result


def test_cli_review_supports_local_base_and_head_without_network(tmp_path: Path, capsys) -> None:
    """本地模式必须构造完整 ReviewRequest，并输出中文进度。"""

    fake = FakeOrchestrator(make_result())

    exit_code = main(
        ["review", "--repo", str(tmp_path), "--base", "main", "--head", "feature"],
        config=Config(runs_dir=tmp_path / "runs"),
        orchestrator_factory=lambda config: fake,
    )

    output = capsys.readouterr()
    assert exit_code == 0
    assert fake.requests == [ReviewRequest(repo_path=str(tmp_path), base_ref="main", head_ref="feature")]
    assert "开始审查" in output.out
    assert "审查完成" in output.out


def test_cli_review_supports_github_pr(tmp_path: Path, capsys) -> None:
    """GitHub 模式必须仅传入 PR URL。"""

    fake = FakeOrchestrator(make_result())
    url = "https://github.com/acme/demo/pull/1"

    exit_code = main(
        ["review", "--pr", url],
        config=Config(runs_dir=tmp_path / "runs"),
        orchestrator_factory=lambda config: fake,
    )

    assert exit_code == 0
    assert fake.requests == [ReviewRequest(pr_url=url)]
    assert "GitHub PR" in capsys.readouterr().out


def test_cli_replay_reads_persisted_events_without_starting_review(tmp_path: Path, capsys) -> None:
    """Replay 基础入口读取历史事件，并显示中文摘要。"""

    run_id = "run-replay"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    event = {
        "id": "evt-1",
        "run_id": run_id,
        "sequence": 1,
        "timestamp": "2026-07-29T00:00:00Z",
        "type": "review.completed",
        "data": {"status": "completed"},
    }
    (run_dir / "events.jsonl").write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")

    exit_code = main(["replay", "--run-id", run_id], config=Config(runs_dir=tmp_path / "runs"))

    output = capsys.readouterr()
    assert exit_code == 0
    assert "回放运行" in output.out
    assert "review.completed" in output.out


def test_cli_invalid_local_arguments_return_nonzero_with_chinese_error(tmp_path: Path, capsys) -> None:
    """本地参数不完整时不得启动审查，且必须返回非零退出码。"""

    exit_code = main(
        ["review", "--repo", str(tmp_path), "--base", "main"],
        config=Config(runs_dir=tmp_path / "runs"),
    )

    output = capsys.readouterr()
    assert exit_code != 0
    assert "错误" in output.err
    assert "--repo、--base 和 --head" in output.err


def test_cli_failed_review_returns_nonzero(tmp_path: Path, capsys) -> None:
    """Orchestrator 返回 failed 时 CLI 必须将失败传播到进程退出码。"""

    fake = FakeOrchestrator(make_result(status="failed"))

    exit_code = main(
        ["review", "--pr", "https://github.com/acme/demo/pull/1"],
        config=Config(runs_dir=tmp_path / "runs"),
        orchestrator_factory=lambda config: fake,
    )

    output = capsys.readouterr()
    assert exit_code == 1
    assert "审查失败" in output.err


def test_cli_missing_replay_returns_nonzero_with_chinese_error(tmp_path: Path, capsys) -> None:
    """不存在的运行不能被静默回放。"""

    exit_code = main(["replay", "--run-id", "missing"], config=Config(runs_dir=tmp_path / "runs"))

    output = capsys.readouterr()
    assert exit_code != 0
    assert "未找到运行" in output.err
