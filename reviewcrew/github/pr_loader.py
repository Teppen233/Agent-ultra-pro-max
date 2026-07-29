"""加载 GitHub PR 或本地 Git 引用之间的差异。"""

from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path

import httpx

from reviewcrew.config import Config
from reviewcrew.diff.parser import parse_unified_diff
from reviewcrew.schemas import PRData, ReviewRequest


_GITHUB_PR = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/pull/(\d+)/?$")


class PRLoadError(RuntimeError):
    """表示 PR 元数据、仓库或 Git 引用无法加载。"""


async def load_pr(request: ReviewRequest, config: Config) -> PRData:
    """根据请求模式加载并标准化 PR 数据。"""

    if request.pr_url is not None:
        return await _load_github(request.pr_url, config)
    if request.repo_path is not None:
        return await _load_local(request, config)
    raise PRLoadError("Replay 请求不包含可加载的 PR 数据")


async def _load_github(pr_url: str, config: Config) -> PRData:
    """通过 GitHub REST API 读取公开或授权 PR。"""

    match = _GITHUB_PR.match(pr_url)
    if match is None:
        raise PRLoadError("GitHub PR 地址格式无效")
    owner, repository, number = match.groups()
    endpoint = f"https://api.github.com/repos/{owner}/{repository}/pulls/{number}"
    headers = {"Accept": "application/vnd.github+json"}
    if config.github_token is not None:
        headers["Authorization"] = f"Bearer {config.github_token.get_secret_value()}"

    try:
        async with httpx.AsyncClient(timeout=config.pr_load_timeout_seconds) as client:
            metadata_response = await client.get(endpoint, headers=headers)
            metadata_response.raise_for_status()
            diff_headers = dict(headers)
            diff_headers["Accept"] = "application/vnd.github.v3.diff"
            diff_response = await client.get(endpoint, headers=diff_headers)
            diff_response.raise_for_status()
    except httpx.HTTPError as error:
        raise PRLoadError(f"加载 GitHub PR 失败：{type(error).__name__}") from error

    metadata = metadata_response.json()
    raw_diff = diff_response.text
    return PRData(
        provider="github",
        repository=f"{owner}/{repository}",
        title=metadata.get("title") or "",
        description=metadata.get("body") or "",
        base_sha=metadata["base"]["sha"],
        head_sha=metadata["head"]["sha"],
        author=(metadata.get("user") or {}).get("login"),
        files=parse_unified_diff(raw_diff),
        raw_diff=raw_diff,
    )


async def _load_local(request: ReviewRequest, config: Config) -> PRData:
    """读取本地仓库两个已校验引用之间的差异。"""

    repo = Path(request.repo_path or "").resolve()
    if not repo.is_dir() or not (repo / ".git").exists():
        raise PRLoadError("本地仓库路径不存在或不是 Git 仓库")
    base_ref = request.base_ref or ""
    head_ref = request.head_ref or ""

    try:
        base_sha, head_sha = await asyncio.gather(
            _git(repo, "rev-parse", "--verify", base_ref, timeout=config.pr_load_timeout_seconds),
            _git(repo, "rev-parse", "--verify", head_ref, timeout=config.pr_load_timeout_seconds),
        )
    except PRLoadError as error:
        raise PRLoadError("无法解析 Git 引用，请检查 base 和 head") from error

    raw_diff = await _git(
        repo,
        "diff",
        "--no-ext-diff",
        f"{base_sha.strip()}...{head_sha.strip()}",
        timeout=config.pr_load_timeout_seconds,
    )
    return PRData(
        provider="local",
        repository=repo.name,
        title=f"本地审查 {base_ref} → {head_ref}",
        description="由本地 Git 引用生成",
        base_sha=base_sha.strip(),
        head_sha=head_sha.strip(),
        files=parse_unified_diff(raw_diff),
        raw_diff=raw_diff,
    )


async def _git(repo: Path, *arguments: str, timeout: float) -> str:
    """在固定仓库目录执行只读 Git 命令。"""

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

    try:
        result = await asyncio.to_thread(run)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PRLoadError(f"Git 命令执行失败：{type(error).__name__}") from error
    if result.returncode != 0:
        message = result.stderr.strip().splitlines()
        summary = message[-1] if message else "未知 Git 错误"
        raise PRLoadError(f"Git 命令失败：{summary}")
    return result.stdout

