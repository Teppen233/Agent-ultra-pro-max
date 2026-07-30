from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from reviewcrew.server.repository import (
    RepositoryPreparationError,
    prepare_repository,
)

GitRun = Callable[..., subprocess.CompletedProcess[str]]


def git_result(
    command: list[str],
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def clean_repository_runner(calls: list[list[str]]) -> GitRun:
    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[1] == "clone":
            Path(command[-1]).mkdir(parents=True)
            return git_result(command)
        if "rev-parse" in command:
            return git_result(command, stdout="true\n")
        if "status" in command:
            return git_result(command)
        if "get-url" in command:
            return git_result(command, stdout="https://github.com/owner/repo.git\n")
        if "pull" in command:
            return git_result(command, stdout="Already up to date.\n")
        raise AssertionError(f"unexpected Git command: {command}")

    return run


@pytest.mark.parametrize("repo_path", [None, "   "])
def test_missing_path_clones_github_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repo_path: str | None,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "reviewcrew.server.repository.subprocess.run",
        clean_repository_runner(calls),
    )

    repository = prepare_repository(
        "https://github.com/Owner/Repo/pull/42",
        repo_path,
        tmp_path / "repos",
    )

    assert repository == (tmp_path / "repos" / "owner__repo").resolve()
    assert calls == [
        [
            "git",
            "clone",
            "https://github.com/owner/repo.git",
            str(repository),
        ]
    ]


@pytest.mark.parametrize("repo_path", ["explicit", None])
def test_existing_repository_is_validated_and_fast_forwarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repo_path: str | None,
) -> None:
    repository = (
        tmp_path / "explicit"
        if repo_path is not None
        else tmp_path / "repos" / "owner__repo"
    )
    repository.mkdir(parents=True)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "reviewcrew.server.repository.subprocess.run",
        clean_repository_runner(calls),
    )

    result = prepare_repository(
        "https://github.com/owner/repo/pull/42",
        str(repository) if repo_path is not None else None,
        tmp_path / "repos",
    )

    assert result == repository.resolve()
    assert calls[-1] == ["git", "-C", str(repository.resolve()), "pull", "--ff-only"]


def test_local_diff_without_repository_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RepositoryPreparationError, match="本地 Diff"):
        prepare_repository("/tmp/change.diff", None, tmp_path / "repos")


def test_automatic_target_rejects_path_separator_characters(tmp_path: Path) -> None:
    with pytest.raises(RepositoryPreparationError, match="必须提供本地仓库路径"):
        prepare_repository(
            r"https://github.com/owner/repo\..\outside/pull/42",
            None,
            tmp_path / "repos",
        )


def test_dirty_repository_is_not_pulled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    calls: list[list[str]] = []

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if "rev-parse" in command:
            return git_result(command, stdout="true\n")
        if "status" in command:
            return git_result(command, stdout=" M local.py\n")
        raise AssertionError(f"unexpected Git command: {command}")

    monkeypatch.setattr("reviewcrew.server.repository.subprocess.run", run)

    with pytest.raises(RepositoryPreparationError, match="未提交修改"):
        prepare_repository("https://github.com/owner/repo/pull/42", str(repository))

    assert not any("pull" in command for command in calls)


def test_generated_profile_directory_does_not_block_pull(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    calls: list[list[str]] = []
    runner = clean_repository_runner(calls)

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "status" in command:
            calls.append(command)
            return git_result(command, stdout="?? profile/\n")
        return runner(command, **kwargs)

    monkeypatch.setattr("reviewcrew.server.repository.subprocess.run", run)

    result = prepare_repository(
        "https://github.com/owner/repo/pull/42",
        str(repository),
    )

    assert result == repository.resolve()
    assert any("pull" in command for command in calls)


def test_mismatched_origin_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    calls: list[list[str]] = []
    runner = clean_repository_runner(calls)

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "get-url" in command:
            calls.append(command)
            return git_result(command, stdout="git@github.com:other/project.git\n")
        return runner(command, **kwargs)

    monkeypatch.setattr("reviewcrew.server.repository.subprocess.run", run)

    with pytest.raises(RepositoryPreparationError, match="other/project"):
        prepare_repository("https://github.com/owner/repo/pull/42", str(repository))


def test_failed_git_command_redacts_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    calls: list[list[str]] = []
    runner = clean_repository_runner(calls)

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "pull" in command:
            return git_result(
                command,
                returncode=1,
                stderr="fatal: https://secret-token@github.com/owner/repo.git denied",
            )
        return runner(command, **kwargs)

    monkeypatch.setattr("reviewcrew.server.repository.subprocess.run", run)

    with pytest.raises(RepositoryPreparationError) as captured:
        prepare_repository("https://github.com/owner/repo/pull/42", str(repository))

    assert "secret-token" not in str(captured.value)
    assert "***@github.com" in str(captured.value)


def test_git_timeout_becomes_actionable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, timeout=120)

    monkeypatch.setattr("reviewcrew.server.repository.subprocess.run", run)

    with pytest.raises(RepositoryPreparationError, match="超时"):
        prepare_repository("https://github.com/owner/repo/pull/42", str(repository))
