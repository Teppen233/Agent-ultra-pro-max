from pathlib import Path

import pytest

from reviewcrew.server.benchmark import (
    BenchmarkConflict,
    BenchmarkInputError,
    BenchmarkStore,
    BenchmarkStoreError,
)

PR_URL = "https://github.com/Owner/Repo/pull/42"


def test_store_reserves_and_reloads_entry(tmp_path: Path) -> None:
    store = BenchmarkStore(tmp_path / "selected.json", tmp_path / "runs")
    entry = store.reserve("run-1", PR_URL)
    assert (entry.repository, entry.repository_name, entry.pr_number) == ("owner/repo", "repo", 42)
    assert BenchmarkStore(store.index_path, tmp_path / "runs").list_entries(set())[0].run_id == "run-1"


def test_store_rejects_duplicate_and_sixth_repository(tmp_path: Path) -> None:
    store = BenchmarkStore(tmp_path / "selected.json", tmp_path / "runs")
    store.reserve("run-1", "https://github.com/acme/repo-1/pull/1")
    with pytest.raises(BenchmarkConflict, match="已存在"):
        store.reserve("duplicate", "https://github.com/acme/repo-1/pull/2")
    for index in range(2, 6):
        store.reserve(f"run-{index}", f"https://github.com/acme/repo-{index}/pull/{index}")
    with pytest.raises(BenchmarkConflict, match="已满"):
        store.reserve("run-6", "https://github.com/acme/repo-6/pull/6")


def test_transitions_and_stale_cleanup(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    store = BenchmarkStore(tmp_path / "selected.json", runs)
    store.reserve("run-1", PR_URL)
    assert store.mark_running("run-1").status == "running"
    (runs / "run-1").mkdir(parents=True)
    (runs / "run-1" / "report.md").write_text("# report", encoding="utf-8")
    assert store.list_entries(set())[0].status == "ready"
    assert store.mark_ready("run-1").completed_at is not None
    store.remove("run-1")
    assert store.list_entries(set()) == []


def test_inactive_reservation_is_removed_but_active_is_kept(tmp_path: Path) -> None:
    store = BenchmarkStore(tmp_path / "selected.json", tmp_path / "runs")
    store.reserve("active", PR_URL)
    store.reserve("other", "https://github.com/owner/other/pull/1")
    (tmp_path / "runs" / "other").mkdir(parents=True)
    entries = store.list_entries({"active"})
    assert [entry.run_id for entry in entries] == ["active"]


def test_invalid_input_and_corrupt_index(tmp_path: Path) -> None:
    path = tmp_path / "selected.json"
    store = BenchmarkStore(path, tmp_path / "runs")
    with pytest.raises(BenchmarkInputError):
        store.reserve("run", "/tmp/change.diff")
    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(BenchmarkStoreError):
        store.list_entries(set())
