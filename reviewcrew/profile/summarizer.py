from __future__ import annotations

import os
import subprocess
from collections import Counter
from pathlib import Path


def _repository_files(repo_path: Path) -> list[Path]:
    tracked = subprocess.run(
        [
            "git",
            "-C",
            str(repo_path),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        capture_output=True,
        timeout=15,
        check=False,
    )
    if tracked.returncode == 0:
        git_files = []
        for value in tracked.stdout.split(b"\0"):
            if not value:
                continue
            path = repo_path / os.fsdecode(value)
            if path.is_file() and "profile" not in path.relative_to(repo_path).parts:
                git_files.append(path)
        return git_files

    files: list[Path] = []
    for root, directories, names in os.walk(repo_path):
        directories[:] = [name for name in directories if name not in {".git", "profile"}]
        files.extend(Path(root) / name for name in names)
    return files


def summarize_architecture(repo_path: Path) -> str:
    files = _repository_files(repo_path)
    top_levels = Counter(path.relative_to(repo_path).parts[0] for path in files)
    languages = Counter(path.suffix or "[no extension]" for path in files)
    readmes = sorted(repo_path.glob("README*"))
    readme_excerpt = ""
    if readmes:
        readme_excerpt = readmes[0].read_text(encoding="utf-8", errors="replace")[:2000].strip()
    lines = [
        "# Repository Architecture Profile",
        "",
        "## Module map",
        "",
        *[f"- `{name}`: {count} tracked files" for name, count in top_levels.most_common(30)],
        "",
        "## Language signals",
        "",
        *[f"- `{suffix}`: {count} files" for suffix, count in languages.most_common(20)],
    ]
    if readme_excerpt:
        lines.extend(["", "## Repository overview", "", readme_excerpt])
    return "\n".join(lines).strip() + "\n"
