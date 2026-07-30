from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


def build_summary(results_path: Path, output_path: Path | None = None) -> str:
    rows = [
        json.loads(line)
        for line in results_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    count = len(rows)
    hits = sum(bool(row["hit"]) for row in rows)
    avg_findings = sum(int(row["finding_count"]) for row in rows) / count if count else 0.0
    avg_seconds = sum(float(row["elapsed_seconds"]) for row in rows) / count if count else 0.0
    matrix: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for row in rows:
        matrix[(str(row["repo"]), str(row["category"]))].append(bool(row["hit"]))

    lines = [
        "# ReviewCrew Evaluation Summary",
        "",
        f"- Cases: {count}",
        f"- Hit rate: {(hits / count * 100) if count else 0:.1f}%",
        f"- Average findings: {avg_findings:.2f}",
        f"- Average duration: {avg_seconds / 60:.2f} min",
        "",
        "## Repository x Category Matrix",
        "",
        "| Repository | Category | Hits | Cases | Rate |",
        "|---|---|---:|---:|---:|",
    ]
    for (repo, category), values in sorted(matrix.items()):
        cell_hits = sum(values)
        lines.append(
            f"| {repo} | {category} | {cell_hits} | {len(values)} | "
            f"{cell_hits / len(values) * 100:.1f}% |"
        )
    markdown = "\n".join(lines) + "\n"
    if output_path is not None:
        output_path.write_text(markdown, encoding="utf-8")
    return markdown
