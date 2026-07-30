from __future__ import annotations

from pathlib import Path

from benchmark.judge import BugLocation, DatasetEntry
from benchmark.run_eval import evaluate
from reviewcrew.models import Finding


class RecordingRunner:
    def __init__(self) -> None:
        self.repo_paths: list[Path] = []

    def review(self, pr_url: str, repo_path: Path) -> list[Finding]:
        del pr_url
        self.repo_paths.append(repo_path)
        return [
            Finding(
                category="security",
                severity="high",
                confidence=0.9,
                file="src/app.py",
                line_start=10,
                line_end=10,
                title="暴露敏感数据",
                reasoning="生产路径可读取凭据。",
                trigger_path="request -> secret",
                suggestion="收窄访问边界。",
            )
        ]


def test_evaluate_uses_repository_worktree_path(tmp_path: Path) -> None:
    entry = DatasetEntry(
        repo="owner/project",
        fork_url="https://example.test/owner/project.git",
        pr_url="https://example.test/owner/project/pull/1",
        base_sha="base",
        head_sha="head",
        bug_desc="敏感数据暴露",
        bug_files=[BugLocation(path="src/app.py", line_start=10, line_end=10)],
        category="security",
    )
    runner = RecordingRunner()

    output = evaluate([entry], runner, tmp_path / "repos", tmp_path / "results")

    assert runner.repo_paths == [tmp_path / "repos" / "project"]
    assert '"hit": true' in output.joinpath("results.jsonl").read_text(encoding="utf-8")
