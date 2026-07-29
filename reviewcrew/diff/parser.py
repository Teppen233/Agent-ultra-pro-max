"""将 Unified Diff 转换为稳定的领域模型。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha1

from reviewcrew.schemas import ChangedFile, DiffHunk


_DIFF_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")
_HUNK_HEADER = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$"
)


@dataclass(slots=True)
class _FileBuilder:
    """解析单个文件时使用的内部可变状态。"""

    old_path: str
    path: str
    status: str = "modified"
    additions: int = 0
    deletions: int = 0
    hunks: list[DiffHunk] = field(default_factory=list)
    binary: bool = False


def parse_unified_diff(raw_diff: str) -> list[ChangedFile]:
    """解析 Git Unified Diff，并返回修改文件列表。"""

    files: list[ChangedFile] = []
    current: _FileBuilder | None = None
    lines = raw_diff.splitlines()
    index = 0

    while index < len(lines):
        line = lines[index]
        header = _DIFF_HEADER.match(line)
        if header:
            if current is not None:
                _append_file(files, current)
            current = _FileBuilder(old_path=header.group(1), path=header.group(2))
            index += 1
            continue
        if current is None:
            index += 1
            continue
        if line.startswith("Binary files ") or line == "GIT binary patch":
            current.binary = True
            index += 1
            continue
        if line.startswith("rename from "):
            current.old_path = line.removeprefix("rename from ")
            current.status = "renamed"
            index += 1
            continue
        if line.startswith("rename to "):
            current.path = line.removeprefix("rename to ")
            current.status = "renamed"
            index += 1
            continue
        if line == "new file mode 100644" or line.startswith("new file mode "):
            current.status = "added"
            index += 1
            continue
        if line.startswith("deleted file mode "):
            current.status = "deleted"
            index += 1
            continue
        hunk_match = _HUNK_HEADER.match(line)
        if hunk_match:
            hunk, index = _parse_hunk(lines, index, current.path, hunk_match)
            current.hunks.append(hunk)
            current.additions += len(hunk.changed_lines)
            current.deletions += sum(
                1 for content_line in hunk.content.splitlines()[1:]
                if content_line.startswith("-") and not content_line.startswith("---")
            )
            continue
        index += 1

    if current is not None:
        _append_file(files, current)
    return files


def changed_line_set(files: list[ChangedFile]) -> dict[str, set[int]]:
    """按文件聚合新增侧的修改行。"""

    return {
        changed_file.path: {
            line
            for hunk in changed_file.hunks
            for line in hunk.changed_lines
        }
        for changed_file in files
    }


def _parse_hunk(
    lines: list[str],
    start_index: int,
    path: str,
    match: re.Match[str],
) -> tuple[DiffHunk, int]:
    """从 hunk header 开始解析到下一个 hunk 或文件。"""

    old_start = int(match.group(1))
    old_count = int(match.group(2) or 1)
    new_start = int(match.group(3))
    new_count = int(match.group(4) or 1)
    old_line = old_start
    new_line = new_start
    changed_lines: list[int] = []
    content = [lines[start_index]]
    index = start_index + 1

    while index < len(lines):
        line = lines[index]
        if _DIFF_HEADER.match(line) or _HUNK_HEADER.match(line):
            break
        content.append(line)
        if line.startswith("+") and not line.startswith("+++"):
            changed_lines.append(new_line)
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            old_line += 1
        elif not line.startswith("\\"):
            old_line += 1
            new_line += 1
        index += 1

    identity = f"{path}:{old_start}:{new_start}:{'|'.join(content)}"
    return (
        DiffHunk(
            id=f"hunk-{sha1(identity.encode('utf-8')).hexdigest()[:12]}",
            file=path,
            old_start=old_start,
            old_count=old_count,
            new_start=new_start,
            new_count=new_count,
            changed_lines=changed_lines,
            content="\n".join(content),
        ),
        index,
    )


def _append_file(files: list[ChangedFile], builder: _FileBuilder) -> None:
    """将内部解析状态转换为不可变领域模型。"""

    if builder.binary:
        return
    files.append(
        ChangedFile(
            path=builder.path,
            old_path=builder.old_path if builder.status == "renamed" else None,
            status=builder.status,
            additions=builder.additions,
            deletions=builder.deletions,
            hunks=builder.hunks,
        )
    )

