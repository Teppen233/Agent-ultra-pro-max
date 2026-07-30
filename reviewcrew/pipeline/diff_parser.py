from __future__ import annotations

import re

from reviewcrew.models import FileDiff, Hunk

LOCKFILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "go.sum",
    "poetry.lock",
}
GENERATED_MARKERS = ("@generated", "# generated", "code generated")
HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _path(value: str) -> str:
    value = value.strip().split("\t", 1)[0]
    if value == "/dev/null":
        return value
    return value[2:] if value.startswith(("a/", "b/")) else value


def _is_whitespace_only(hunks: list[Hunk]) -> bool:
    removed: list[str] = []
    added: list[str] = []
    for hunk in hunks:
        removed.extend(
            line[1:] for line in hunk.lines if line.startswith("-") and not line.startswith("---")
        )
        added.extend(
            line[1:] for line in hunk.lines if line.startswith("+") and not line.startswith("+++")
        )
    return ["".join(line.split()) for line in removed] == ["".join(line.split()) for line in added]


def _is_generated(hunks: list[Hunk]) -> bool:
    content = "\n".join(line[1:] for hunk in hunks for line in hunk.lines if line[:1] in {" ", "+"})
    head = content[:1000].lower()
    return any(marker in head for marker in GENERATED_MARKERS)


def _build_file(old_path: str, new_path: str, hunks: list[Hunk], renamed: bool) -> FileDiff | None:
    path = old_path if new_path == "/dev/null" else new_path
    if path.rsplit("/", 1)[-1] in LOCKFILES:
        return None
    if _is_generated(hunks) or _is_whitespace_only(hunks):
        return None
    if old_path == "/dev/null":
        change_type = "add"
    elif new_path == "/dev/null":
        change_type = "delete"
    elif renamed or old_path != new_path:
        change_type = "rename"
    else:
        change_type = "modify"
    return FileDiff(
        path=path,
        old_path=old_path if change_type == "rename" else None,
        change_type=change_type,
        hunks=hunks,
    )


def parse_diff(raw: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    old_path = ""
    new_path = ""
    renamed = False
    hunks: list[Hunk] = []
    current: Hunk | None = None

    def flush() -> None:
        nonlocal hunks, current
        if old_path and new_path:
            parsed = _build_file(old_path, new_path, hunks, renamed)
            if parsed is not None:
                files.append(parsed)
        hunks = []
        current = None

    for line in raw.splitlines():
        if line.startswith("diff --git "):
            flush()
            parts = line.split()
            old_path = _path(parts[2])
            new_path = _path(parts[3])
            renamed = False
        elif line.startswith("rename from "):
            old_path = line.removeprefix("rename from ")
            renamed = True
        elif line.startswith("rename to "):
            new_path = line.removeprefix("rename to ")
            renamed = True
        elif line.startswith("--- "):
            old_path = _path(line.removeprefix("--- "))
        elif line.startswith("+++ "):
            new_path = _path(line.removeprefix("+++ "))
        elif match := HUNK_HEADER.match(line):
            current = Hunk(
                old_start=int(match.group(1)),
                old_count=int(match.group(2) or "1"),
                new_start=int(match.group(3)),
                new_count=int(match.group(4) or "1"),
                lines=[],
            )
            hunks.append(current)
        elif current is not None and line[:1] in {" ", "+", "-", "\\"}:
            current.lines.append(line)
    flush()
    return files
