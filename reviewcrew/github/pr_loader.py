"""PR Loader —— GitHub API 和本地 Git 仓库两种模式的数据加载。

支持：
- GitHub 模式：通过 REST API 获取 PR 元数据和 diff
- 本地模式：在指定仓库路径执行 git diff
"""

from __future__ import annotations

import asyncio
import re
import urllib.parse
from pathlib import Path

import httpx

from ..config import Config
from ..diff.parser import parse_unified_diff
from ..schemas import PRData, ReviewRequest

# GitHub PR URL 解析正则
_PR_URL_RE = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)/?(\?.*)?$"
)


def parse_pr_url(url: str) -> tuple[str, str, int]:
    """解析 GitHub PR URL，返回 (owner, repo, number)。

    Args:
        url: GitHub PR URL，如 https://github.com/acme/demo/pull/7

    Returns:
        (owner, repo, pull_number)

    Raises:
        ValueError: URL 格式不合法
    """
    m = _PR_URL_RE.match(url)
    if not m:
        raise ValueError(
            f"无效的 GitHub PR URL: {url}。"
            f"期望格式: https://github.com/<owner>/<repo>/pull/<number>"
        )
    return m.group(1), m.group(2), int(m.group(3))


async def load_pr(request: ReviewRequest, config: Config) -> PRData:
    """加载 PR 数据，根据 ReviewRequest 自动选择模式。

    Args:
        request: 审查请求，包含 pr_url 或本地仓库参数
        config: 全局配置

    Returns:
        标准化的 PRData

    Raises:
        ValueError: 参数无效
        RuntimeError: 网络或 Git 命令失败
    """
    if request.pr_url:
        return await _load_github(request.pr_url, config)
    elif request.repo_path and request.base_ref and request.head_ref:
        return await _load_local(request.repo_path, request.base_ref, request.head_ref, config)
    else:
        raise ValueError("无效的审查请求：必须提供 pr_url 或本地仓库参数")


# ============================================================================
# GitHub Loader
# ============================================================================


async def _load_github(pr_url: str, config: Config) -> PRData:
    """从 GitHub API 加载 PR 数据和 diff。

    GitHub Token 可选；未提供时使用无认证请求（限流较低）。
    """
    owner, repo, number = parse_pr_url(pr_url)
    token = config.github_token.get_secret_value() if config.github_token else ""

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ReviewCrew/0.1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    api_base = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 获取 PR 元数据
        resp = await client.get(api_base, headers=headers)
        if resp.status_code == 404:
            raise RuntimeError(
                f"PR 不存在或无权访问: {pr_url}（HTTP 404）"
            )
        if resp.status_code == 403:
            raise RuntimeError(
                f"GitHub API 限流或权限不足: {pr_url}（HTTP 403）。"
                f"建议设置 GITHUB_TOKEN 环境变量"
            )
        resp.raise_for_status()
        pr_data = resp.json()

        # 获取 PR diff
        diff_headers = {**headers, "Accept": "application/vnd.github.v3.diff"}
        diff_resp = await client.get(api_base, headers=diff_headers)
        diff_resp.raise_for_status()
        raw_diff = diff_resp.text

    files = parse_unified_diff(raw_diff)

    return PRData(
        provider="github",
        repository=f"{owner}/{repo}",
        title=pr_data.get("title", ""),
        description=pr_data.get("body", "") or "",
        base_sha=pr_data.get("base", {}).get("sha", ""),
        head_sha=pr_data.get("head", {}).get("sha", ""),
        author=pr_data.get("user", {}).get("login"),
        files=files,
        raw_diff=raw_diff,
    )


# ============================================================================
# Local Loader
# ============================================================================


async def _load_local(
    repo_path: str,
    base_ref: str,
    head_ref: str,
    config: Config,
) -> PRData:
    """从本地 Git 仓库加载 base/head diff。

    使用 git diff 命令获取差异，不依赖网络。
    """
    repo = Path(repo_path)
    if not repo.exists() or not (repo / ".git").exists():
        raise ValueError(
            f"仓库路径不存在或不是 Git 仓库: {repo_path}"
        )

    # 验证 ref 存在
    for ref in [base_ref, head_ref]:
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "--verify", ref,
            cwd=str(repo),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise ValueError(
                f"引用不存在: {ref}（仓库 {repo_path}）\n"
                f"{stderr.decode('utf-8', errors='replace').strip()}"
            )

    # 获取标题（head 的最近提交信息）
    proc = await asyncio.create_subprocess_exec(
        "git", "log", "-1", "--format=%s", head_ref,
        cwd=str(repo),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    title = stdout.decode("utf-8", errors="replace").strip() or f"{base_ref}..{head_ref}"

    # 获取 diff
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", f"{base_ref}...{head_ref}",
        cwd=str(repo),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"git diff 失败: {stderr.decode('utf-8', errors='replace').strip()}"
        )
    raw_diff = stdout.decode("utf-8", errors="replace")

    # 获取 SHA
    proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", base_ref,
        cwd=str(repo),
        stdout=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    base_sha = stdout.decode().strip()

    proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", head_ref,
        cwd=str(repo),
        stdout=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    head_sha = stdout.decode().strip()

    files = parse_unified_diff(raw_diff)

    return PRData(
        provider="local",
        repository=str(repo),
        title=title,
        description="",
        base_sha=base_sha,
        head_sha=head_sha,
        author=None,
        files=files,
        raw_diff=raw_diff,
    )
