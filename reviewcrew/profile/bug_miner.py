from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path

KEYWORDS = (
    "injection",
    "race",
    "deadlock",
    "leak",
    "overflow",
    "auth",
    "permission",
    "null",
    "boundary",
    "timeout",
)


def mine_bug_patterns(repo_path: Path, limit: int = 10) -> list[str]:
    process = subprocess.run(
        [
            "git",
            "-C",
            str(repo_path),
            "log",
            "--all",
            "--regexp-ignore-case",
            "--grep=fix|bug",
            "--pretty=format:%s %b",
            "--max-count=100",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if process.returncode != 0:
        return []
    messages = [line.strip() for line in process.stdout.splitlines() if line.strip()]
    counts: Counter[str] = Counter()
    for message in messages:
        lower = message.lower()
        matched = [keyword for keyword in KEYWORDS if keyword in lower]
        for keyword in matched or re.findall(r"[a-z][a-z0-9_-]{3,}", lower)[:2]:
            counts[keyword] += 1
    return [
        f"Historical fixes frequently mention {name} ({count} commits)."
        for name, count in counts.most_common(limit)
    ]
