from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from pydantic import BaseModel, Field

from reviewcrew.server.repository import github_repository

_PR_NUMBER = re.compile(
    r"^https?://github\.com/[A-Za-z0-9.-]+/[A-Za-z0-9_.-]+/pull/(\d+)(?:[/?#].*)?$",
    re.IGNORECASE,
)
_LOCK_GUARD = threading.Lock()
_LOCKS: dict[Path, threading.RLock] = {}


class BenchmarkConflict(RuntimeError):
    """Raised when a benchmark capacity or uniqueness constraint is violated."""


class BenchmarkInputError(ValueError):
    """Raised when a review URL cannot be added to the benchmark."""


class BenchmarkStoreError(RuntimeError):
    """Raised when the persisted benchmark index cannot be read safely."""


class BenchmarkIdentity(BaseModel):
    repository: str
    repository_name: str
    pr_url: str
    pr_number: int = Field(gt=0)


class BenchmarkEntry(BaseModel):
    run_id: str
    repository: str
    repository_name: str
    pr_url: str
    pr_number: int = Field(gt=0)
    status: Literal["reserved", "running", "ready"] = "reserved"
    created_at: float
    completed_at: float | None = None


def _lock_for(path: Path) -> threading.RLock:
    key = path.resolve()
    with _LOCK_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _identity(pr_url: str) -> BenchmarkIdentity:
    normalized = pr_url.strip()
    repository = github_repository(normalized)
    match = _PR_NUMBER.fullmatch(normalized)
    if repository is None or match is None:
        raise BenchmarkInputError("Benchmark 只支持 GitHub PR 地址。")
    owner, name = repository
    return BenchmarkIdentity(
        repository=f"{owner}/{name}",
        repository_name=name,
        pr_url=normalized,
        pr_number=int(match.group(1)),
    )


class BenchmarkStore:
    def __init__(self, index_path: Path, runs_dir: Path, capacity: int = 5) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.index_path = index_path
        self.runs_dir = runs_dir
        self.capacity = capacity
        self._lock = _lock_for(index_path)

    def _read(self) -> list[BenchmarkEntry]:
        if not self.index_path.exists():
            return []
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("index must be a list")
            return [BenchmarkEntry.model_validate(item) for item in payload]
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise BenchmarkStoreError(
                f"Benchmark 索引损坏，未覆盖原文件：{self.index_path}"
            ) from error

    def _write(self, entries: list[BenchmarkEntry]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            [entry.model_dump(mode="json") for entry in entries],
            ensure_ascii=False,
            indent=2,
        )
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.index_path.parent, delete=False
            ) as temporary:
                temporary.write(payload)
                temporary.flush()
                temp_path = Path(temporary.name)
            temp_path.replace(self.index_path)
        except OSError as error:
            try:
                temp_path.unlink(missing_ok=True)
            except (UnboundLocalError, OSError):
                pass
            raise BenchmarkStoreError("无法写入 Benchmark 索引。") from error

    def list_entries(self, active_run_ids: set[str]) -> list[BenchmarkEntry]:
        with self._lock:
            entries = self._read()
            changed = False
            retained: list[BenchmarkEntry] = []
            for entry in entries:
                report = self.runs_dir / entry.run_id / "report.md"
                if entry.status != "ready" and report.exists():
                    entry = entry.model_copy(update={"status": "ready", "completed_at": time.time()})
                    changed = True
                elif (
                    entry.status != "ready"
                    and entry.run_id not in active_run_ids
                    and (self.runs_dir / entry.run_id).exists()
                ):
                    changed = True
                    continue
                retained.append(entry)
            if changed:
                self._write(retained)
            return retained

    def get(self, run_id: str) -> BenchmarkEntry | None:
        with self._lock:
            return next((entry for entry in self._read() if entry.run_id == run_id), None)

    def reserve(self, run_id: str, pr_url: str) -> BenchmarkEntry:
        identity = _identity(pr_url)
        with self._lock:
            entries = self._read()
            if any(entry.repository == identity.repository for entry in entries):
                raise BenchmarkConflict(f"仓库 {identity.repository} 已存在于 Benchmark。")
            if len(entries) >= self.capacity:
                raise BenchmarkConflict(f"Benchmark 已满，最多只能添加 {self.capacity} 个仓库。")
            entry = BenchmarkEntry(
                run_id=run_id, **identity.model_dump(), created_at=time.time()
            )
            self._write([*entries, entry])
            return entry

    def _transition(self, run_id: str, status: Literal["running", "ready"]) -> BenchmarkEntry:
        with self._lock:
            entries = self._read()
            for index, entry in enumerate(entries):
                if entry.run_id == run_id:
                    updated = entry.model_copy(
                        update={
                            "status": status,
                            "completed_at": time.time() if status == "ready" else entry.completed_at,
                        }
                    )
                    entries[index] = updated
                    self._write(entries)
                    return updated
        raise KeyError(run_id)

    def mark_running(self, run_id: str) -> BenchmarkEntry:
        return self._transition(run_id, "running")

    def mark_ready(self, run_id: str) -> BenchmarkEntry:
        return self._transition(run_id, "ready")

    def remove(self, run_id: str) -> None:
        with self._lock:
            entries = self._read()
            retained = [entry for entry in entries if entry.run_id != run_id]
            if len(retained) != len(entries):
                self._write(retained)
