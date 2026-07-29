"""安全读取仓库内部文件范围。"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from reviewcrew.schemas import CodeEvidence


class ToolAccessError(RuntimeError):
    """表示工具请求违反仓库路径或读取限制。"""


def resolve_repo_path(repo: Path, relative_path: str) -> Path:
    """解析仓库内路径，并拒绝路径穿越。"""

    root = Path(repo).resolve()
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise ToolAccessError("工具只允许访问仓库范围内的文件")
    return target


def safe_read(repo: Path, relative_path: str, start: int, end: int) -> CodeEvidence:
    """读取仓库文件的闭区间行号，单次最多三百行。"""

    if start < 1 or end < start:
        raise ToolAccessError("文件读取行号范围无效")
    if end - start + 1 > 300:
        raise ToolAccessError("单次文件读取不能超过 300 行")
    target = resolve_repo_path(repo, relative_path)
    if not target.is_file():
        raise ToolAccessError("目标文件不存在或不是普通文件")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    actual_end = min(end, len(lines))
    content = "\n".join(lines[start - 1 : actual_end])
    digest = sha256(content.encode("utf-8")).hexdigest()
    return CodeEvidence(
        source="read_file_range",
        file=target.relative_to(Path(repo).resolve()).as_posix(),
        start_line=start,
        end_line=max(start, actual_end),
        description=f"读取文件第 {start} 至 {actual_end} 行",
        content=content,
        content_hash=digest,
    )

