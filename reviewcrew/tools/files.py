"""安全文件读取 —— 读取仓库内代码片段，拒绝路径穿越和越界访问。"""

from __future__ import annotations

from pathlib import Path

from ..schemas import CodeEvidence


def safe_read(
    repo: Path,
    relative_path: str,
    start: int,
    end: int,
) -> CodeEvidence:
    """安全读取仓库内的文件范围。

    拒绝路径穿越和绝对路径，防止 Agent 读取仓库外文件。

    Args:
        repo: 仓库根目录
        relative_path: 相对于仓库的文件路径
        start: 起始行号（1-indexed）
        end: 结束行号（1-indexed，含）

    Returns:
        CodeEvidence 对象，包含文件内容和位置信息

    Raises:
        ValueError: 路径不在仓库范围内
        FileNotFoundError: 文件不存在
    """
    # 安全检查：拒绝路径穿越
    full_path = (repo / relative_path).resolve()
    repo_resolved = repo.resolve()

    if not str(full_path).startswith(str(repo_resolved) + ("\\" if "\\" in str(repo_resolved) else "/")):
        raise ValueError(f"路径 {relative_path} 不在仓库范围内")

    if not full_path.is_file():
        raise FileNotFoundError(f"文件不存在: {relative_path}")

    # 读取指定范围
    lines = full_path.read_text(encoding="utf-8", errors="replace").split("\n")

    # 裁剪到实际行数
    actual_end = min(end, len(lines))
    actual_start = max(1, min(start, actual_end))

    selected = lines[actual_start - 1 : actual_end]
    content = "\n".join(selected)

    # 推断语言
    suffix = full_path.suffix
    lang_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".go": "go",
        ".java": "java",
        ".rb": "ruby",
        ".vue": "vue",
        ".sql": "sql",
    }
    language = lang_map.get(suffix, "")

    return CodeEvidence(
        file=relative_path,
        line_start=actual_start,
        line_end=actual_end,
        content=content,
        language=language,
    )
