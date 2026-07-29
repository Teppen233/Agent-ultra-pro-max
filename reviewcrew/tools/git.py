"""提供受限、只读的 Git 历史工具。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from reviewcrew.schemas import TextEvidence
from reviewcrew.tools.files import resolve_repo_path


def git_history(repo: Path, relative_path: str, limit: int = 10) -> list[TextEvidence]:
    """返回文件最近提交的 SHA、主题和作者。"""

    resolve_repo_path(repo, relative_path)
    result = _run_git(repo, "log", f"-{limit}", "--format=%H%x1f%s%x1f%an", "--", relative_path)
    evidence: list[TextEvidence] = []
    for line in result.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        sha, subject, author = parts
        evidence.append(
            TextEvidence(
                source="git_history",
                title=subject,
                content=f"提交 {sha}，作者 {author}",
                reference=sha,
            )
        )
    return evidence


def git_blame(repo: Path, relative_path: str, start: int, end: int) -> list[TextEvidence]:
    """读取文件指定行范围的 blame 摘要。"""

    resolve_repo_path(repo, relative_path)
    if end < start or end - start + 1 > 100:
        raise ValueError("Git blame 单次最多查询 100 行")
    output = _run_git(repo, "blame", "--line-porcelain", f"-L{start},{end}", "--", relative_path)
    return [
        TextEvidence(
            source="git_blame",
            title=f"{relative_path}:{start}-{end}",
            content=output[:12_000],
            reference=relative_path,
        )
    ]


def git_show(repo: Path, revision: str) -> TextEvidence:
    """读取指定提交的有限摘要和差异。"""

    output = _run_git(repo, "show", "--stat", "--format=fuller", revision)
    return TextEvidence(source="git_show", title=revision, content=output[:20_000], reference=revision)


def _run_git(repo: Path, *arguments: str) -> str:
    """执行固定工作目录的只读 Git 子进程。"""

    result = subprocess.run(
        ["git", *arguments],
        cwd=Path(repo).resolve(),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Git 查询失败：{result.stderr.strip()}")
    return result.stdout

