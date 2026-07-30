from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from reviewcrew.server.benchmark import BenchmarkEntry, benchmark_identity

GREPTILE_BENCHMARK_CAPACITY = 10


class GreptileManifestRun(BaseModel):
    run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=160)
    status: Literal["running", "done", "failed"]
    repo: str = Field(min_length=1)
    pr_url: str = Field(min_length=1)


def load_greptile_entries(
    manifest_path: Path,
    runs_dir: Path,
    active_run_ids: set[str],
) -> list[BenchmarkEntry] | None:
    """Return curated entries, or None when no curated manifest is configured."""
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []

    entries: list[BenchmarkEntry] = []
    for raw in payload[:GREPTILE_BENCHMARK_CAPACITY]:
        try:
            manifest_run = GreptileManifestRun.model_validate(raw)
            identity = benchmark_identity(manifest_run.pr_url)
        except (ValidationError, ValueError):
            continue
        if identity.repository != manifest_run.repo.lower():
            continue

        directory = runs_dir / manifest_run.run_id
        report_path = directory / "report.md"
        if report_path.exists():
            status = "ready"
            completed_at = report_path.stat().st_mtime
        elif manifest_run.run_id in active_run_ids:
            status = "running"
            completed_at = None
        else:
            status = "reserved"
            completed_at = None
        created_at = directory.stat().st_mtime if directory.exists() else 0.0
        entries.append(
            BenchmarkEntry(
                run_id=manifest_run.run_id,
                name=manifest_run.name,
                **identity.model_dump(),
                status=status,
                created_at=created_at,
                completed_at=completed_at,
            )
        )
    return entries
