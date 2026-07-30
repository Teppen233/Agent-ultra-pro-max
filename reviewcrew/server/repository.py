from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

GITHUB_PR = re.compile(
    r"^https?://github\.com/([A-Za-z0-9.-]+)/([A-Za-z0-9_.-]+)/pull/\d+(?:[/?#].*)?$"
)
GITHUB_REMOTE = re.compile(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?$")
URL_CREDENTIALS = re.compile(r"(https?://)[^/@\s]+@")
GIT_COMMAND_TIMEOUT_SECONDS = 30
GIT_PULL_TIMEOUT_SECONDS: int | None = None
GIT_CLONE_TIMEOUT_SECONDS: int | None = None

_LOCKS_GUARD = threading.Lock()
_REPOSITORY_LOCKS: dict[Path, threading.Lock] = {}


class RepositoryPreparationError(RuntimeError):
    pass


def github_repository(value: str) -> tuple[str, str] | None:
    match = GITHUB_PR.fullmatch(value.strip())
    if match is None:
        return None
    return match.group(1).lower(), match.group(2).lower()


def _github_remote(value: str) -> tuple[str, str] | None:
    match = GITHUB_REMOTE.search(value.strip())
    if match is None:
        return None
    return match.group(1).lower(), match.group(2).lower()


def _sanitize_git_output(value: str) -> str:
    return URL_CREDENTIALS.sub(r"\1***@", value.strip())


def _run_git(
    arguments: list[str],
    action: str,
    timeout: int | None = GIT_COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    command = ["git", *arguments]
    environment = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
    }
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=environment,
        )
    except subprocess.TimeoutExpired as error:
        raise RepositoryPreparationError(f"{action}超时，请检查网络或 Git 状态。") from error
    if result.returncode == 0:
        return result
    detail = _sanitize_git_output(result.stderr or result.stdout)
    message = detail or "Git 未返回错误详情"
    raise RepositoryPreparationError(f"{action}失败：{message}")


def _repository_lock(path: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _REPOSITORY_LOCKS.setdefault(path, threading.Lock())


def _validate_worktree(repository: Path) -> None:
    if not repository.is_dir():
        raise RepositoryPreparationError(f"本地仓库目录不存在或不是目录：{repository}")
    try:
        result = _run_git(
            ["-C", str(repository), "rev-parse", "--is-inside-work-tree"],
            "校验本地仓库",
        )
    except RepositoryPreparationError as error:
        if "超时" in str(error):
            raise
        raise RepositoryPreparationError(f"不是有效 Git 仓库：{repository}") from error
    if result.stdout.strip() != "true":
        raise RepositoryPreparationError(f"不是有效 Git 仓库：{repository}")


def _ensure_clean(repository: Path) -> None:
    status = _run_git(
        ["-C", str(repository), "status", "--porcelain", "--untracked-files=normal"],
        "检查工作区",
    )
    changes = [line for line in status.stdout.splitlines() if line != "?? profile/"]
    if changes:
        raise RepositoryPreparationError(
            f"仓库存在未提交修改，已停止自动更新：{repository}"
        )


def _validate_origin(repository: Path, expected: tuple[str, str] | None) -> None:
    if expected is None:
        return
    remote = _run_git(
        ["-C", str(repository), "remote", "get-url", "origin"],
        "读取 origin",
    )
    actual = _github_remote(remote.stdout)
    if actual == expected:
        return
    expected_name = "/".join(expected)
    actual_name = "/".join(actual) if actual is not None else "无法识别"
    raise RepositoryPreparationError(
        f"PR 属于 {expected_name}，但本地仓库 origin 是 {actual_name}，请使用匹配的仓库目录。"
    )


def _update_repository(repository: Path, expected: tuple[str, str] | None) -> Path:
    _validate_worktree(repository)
    _ensure_clean(repository)
    _validate_origin(repository, expected)
    _run_git(
        ["-C", str(repository), "pull", "--ff-only"],
        "更新仓库",
        GIT_PULL_TIMEOUT_SECONDS,
    )
    return repository


def prepare_repository(
    pr_url: str,
    repo_path: str | None,
    repos_dir: Path = Path("repos"),
) -> Path:
    expected = github_repository(pr_url)
    normalized_path = repo_path.strip() if repo_path else ""
    if normalized_path:
        repository = Path(normalized_path).expanduser().resolve()
        with _repository_lock(repository):
            return _update_repository(repository, expected)

    if expected is None:
        raise RepositoryPreparationError("本地 Diff 或非 GitHub PR 必须提供本地仓库路径。")

    owner, name = expected
    repository = (repos_dir / f"{owner}__{name}").resolve()
    with _repository_lock(repository):
        if repository.exists():
            return _update_repository(repository, expected)
        repository.parent.mkdir(parents=True, exist_ok=True)
        clone_url = f"https://github.com/{owner}/{name}.git"
        try:
            _run_git(
                ["clone", clone_url, str(repository)],
                "克隆仓库",
                GIT_CLONE_TIMEOUT_SECONDS,
            )
        except RepositoryPreparationError:
            if repository.exists():
                shutil.rmtree(repository)
            raise
        return repository
