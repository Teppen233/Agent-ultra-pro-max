"""Unified Diff 解析器 —— 逐行状态机解析 Git diff 输出。

不依赖 GitHub 特定 HTML，纯文本解析 unified diff 格式。
过滤二进制文件；lockfile 和生成文件标记为 skipped warning。
"""

from __future__ import annotations

import re

from ..schemas import ChangedFile, DiffHunk


# 匹配 diff 文件头信息
_RE_FILE_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")
_RE_OLD_MODE = re.compile(r"^old mode (\d+)$")
_RE_NEW_MODE = re.compile(r"^new mode (\d+)$")
_RE_NEW_FILE = re.compile(r"^new file mode (\d+)$")
_RE_DELETED_FILE = re.compile(r"^deleted file mode (\d+)$")
_RE_RENAME_FROM = re.compile(r"^rename from (.+)$")
_RE_RENAME_TO = re.compile(r"^rename to (.+)$")
_RE_INDEX = re.compile(r"^index [0-9a-f]+\.\.[0-9a-f]+")
_RE_HUNK_HEADER = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$"
)
_RE_BINARY = re.compile(r"^Binary files .+ differ$")

# 应跳过的文件模式
_SKIP_PATTERNS = [
    r"package-lock\.json$",
    r"yarn\.lock$",
    r"pnpm-lock\.yaml$",
    r"poetry\.lock$",
    r"Pipfile\.lock$",
    r".*\.min\.(js|css)$",
    r".*\.generated\..*$",
]


def _should_skip_file(path: str) -> bool:
    """判断文件是否应跳过（lockfile、minified、generated 等）。"""
    return any(re.search(pattern, path) for pattern in _SKIP_PATTERNS)


def parse_unified_diff(raw_diff: str) -> list[ChangedFile]:
    """解析 unified diff 文本为 ChangedFile 列表。

    使用逐行状态机，支持：
    - 新增 (added)、修改 (modified)、删除 (deleted)、重命名 (renamed)
    - 多 hunk 文件
    - 二进制文件跳过
    - /dev/null 处理

    Args:
        raw_diff: Git unified diff 原始文本

    Returns:
        变更文件列表，按 diff 出现顺序排列
    """
    if not raw_diff.strip():
        return []

    lines = raw_diff.split("\n")
    files: list[ChangedFile] = []
    current_file: dict | None = None
    current_hunk: dict | None = None

    i = 0
    while i < len(lines):
        line = lines[i]

        # 文件头：diff --git a/... b/...
        m = _RE_FILE_HEADER.match(line)
        if m:
            # 保存上一个文件
            if current_file is not None:
                _finalize_file(files, current_file, current_hunk)

            old_path = m.group(1)
            new_path = m.group(2)
            current_file = {
                "old_path": old_path if old_path != "/dev/null" else None,
                "new_path": new_path if new_path != "/dev/null" else None,
                "status": "modified",
                "hunks": [],
                "additions": 0,
                "deletions": 0,
                "is_binary": False,
            }
            current_hunk = None
            i += 1
            continue

        # 二进制文件
        if _RE_BINARY.match(line):
            if current_file:
                current_file["is_binary"] = True
            i += 1
            continue

        # 文件模式
        if _RE_NEW_FILE.match(line):
            if current_file:
                current_file["status"] = "added"
            i += 1
            continue

        if _RE_DELETED_FILE.match(line):
            if current_file:
                current_file["status"] = "deleted"
            i += 1
            continue

        # 重命名
        m = _RE_RENAME_FROM.match(line)
        if m:
            if current_file:
                current_file["old_path"] = m.group(1)
            i += 1
            continue

        m = _RE_RENAME_TO.match(line)
        if m:
            if current_file:
                current_file["status"] = "renamed"
            i += 1
            continue

        # index / old mode / new mode 行：跳过
        if _RE_INDEX.match(line) or _RE_OLD_MODE.match(line) or _RE_NEW_MODE.match(line):
            i += 1
            continue

        # --- / +++ 行：跳过
        if line.startswith("--- ") or line.startswith("+++ "):
            i += 1
            continue

        # Hunk 头
        m = _RE_HUNK_HEADER.match(line)
        if m:
            if current_hunk is not None and current_file is not None:
                _finalize_hunk(current_file, current_hunk)

            old_start = int(m.group(1))
            old_count = int(m.group(2)) if m.group(2) else 1
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) else 1

            current_hunk = {
                "old_start": old_start,
                "old_count": old_count,
                "new_start": new_start,
                "new_count": new_count,
                "changed_lines": [],
                "content_lines": [],
            }
            i += 1

            # 收集 hunk 内行
            new_line = new_start
            while i < len(lines):
                hunk_line = lines[i]
                # 检查是否到了下一个 hunk 或文件头
                if _RE_HUNK_HEADER.match(hunk_line) or _RE_FILE_HEADER.match(hunk_line):
                    break

                if current_hunk is not None:
                    current_hunk["content_lines"].append(hunk_line)

                if hunk_line.startswith("+") and not hunk_line.startswith("+++"):
                    if current_hunk is not None:
                        current_hunk["changed_lines"].append(new_line)
                    if current_file is not None:
                        current_file["additions"] += 1
                    new_line += 1
                elif hunk_line.startswith("-") and not hunk_line.startswith("---"):
                    if current_file is not None:
                        current_file["deletions"] += 1
                elif not hunk_line.startswith("\\"):
                    # 上下文行（空格开头）或空行
                    new_line += 1

                i += 1
            continue

        i += 1

    # 保存最后一个文件和 hunk
    if current_file is not None:
        _finalize_file(files, current_file, current_hunk)

    # 过滤二进制和应跳过的文件
    result: list[ChangedFile] = []
    for f_dict in files:
        if f_dict.get("is_binary"):
            continue
        path = f_dict["new_path"] or f_dict.get("old_path", "")
        if _should_skip_file(path):
            continue
        result.append(_dict_to_changed_file(f_dict))

    return result


def _finalize_file(
    files: list[dict],
    current_file: dict | None,
    current_hunk: dict | None,
) -> None:
    """完成当前文件的处理。"""
    if current_file is None:
        return
    if current_hunk is not None:
        _finalize_hunk(current_file, current_hunk)
    files.append(current_file)


def _finalize_hunk(file_dict: dict, hunk_dict: dict) -> None:
    """完成当前 hunk 的处理。"""
    file_dict.setdefault("hunks", []).append(hunk_dict)


def _dict_to_changed_file(d: dict) -> ChangedFile:
    """将内部字典转换为 ChangedFile 模型。"""
    path = d.get("new_path", "")
    if not path:
        path = d.get("old_path", "")

    hunks = []
    for h in d.get("hunks", []):
        hunks.append(
            DiffHunk(
                id=f"h-{path}-{h['new_start']}",
                file=path,
                old_start=h["old_start"],
                old_count=h["old_count"],
                new_start=h["new_start"],
                new_count=h["new_count"],
                changed_lines=h["changed_lines"],
                content="\n".join(h.get("content_lines", [])),
            )
        )

    return ChangedFile(
        path=path,
        old_path=d.get("old_path") if d.get("status") == "renamed" else None,
        status=d["status"],
        additions=d.get("additions", 0),
        deletions=d.get("deletions", 0),
        hunks=hunks,
    )


def changed_line_set(files: list[ChangedFile]) -> dict[str, set[int]]:
    """从 ChangedFile 列表构建文件到变更行号集合的映射。

    Args:
        files: 变更文件列表

    Returns:
        文件路径到变更行号集合的映射
    """
    result: dict[str, set[int]] = {}
    for f in files:
        lines: set[int] = set()
        for h in f.hunks:
            lines.update(h.changed_lines)
        if lines:
            result[f.path] = lines
    return result
