"""事件存储测试 —— 验证 PipelineEvent 的顺序、持久化和查询。"""

import json
from pathlib import Path

import pytest


def test_events_receive_monotonic_sequence(tmp_path: Path):
    """事件序列号必须单调递增且按顺序持久化。"""
    from reviewcrew.events import EventStore

    store = EventStore(tmp_path)
    run_id = store.create_run()

    first = store.emit(run_id, "review.started", {})
    second = store.emit(run_id, "stage.started", {"stage": "loading_pr"})

    assert first.sequence == 1
    assert second.sequence == 2

    events = store.read(run_id)
    assert events == [first, second]


def test_events_persist_to_jsonl(tmp_path: Path):
    """事件必须持久化到 runs/{run_id}/events.jsonl。"""
    from reviewcrew.events import EventStore

    store = EventStore(tmp_path)
    run_id = store.create_run()
    store.emit(run_id, "review.started", {"repo": "test"})

    events_file = tmp_path / run_id / "events.jsonl"
    assert events_file.exists()

    lines = events_file.read_text().strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["type"] == "review.started"
    assert data["data"]["repo"] == "test"


def test_events_read_returns_empty_for_nonexistent_run(tmp_path: Path):
    """不存在的 run 返回空列表。"""
    from reviewcrew.events import EventStore

    store = EventStore(tmp_path)
    assert store.read("nonexistent") == []


def test_events_multiple_runs_isolated(tmp_path: Path):
    """不同 run 的事件互不干扰。"""
    from reviewcrew.events import EventStore

    store = EventStore(tmp_path)
    run_a = store.create_run()
    run_b = store.create_run()

    store.emit(run_a, "review.started", {})
    store.emit(run_b, "review.started", {})

    assert len(store.read(run_a)) == 1
    assert len(store.read(run_b)) == 1


def test_events_emit_fails_for_unknown_run(tmp_path: Path):
    """向未创建的 run 发射事件应抛出异常。"""
    from reviewcrew.events import EventStore

    store = EventStore(tmp_path)
    with pytest.raises(ValueError, match="不存在"):
        store.emit("ghost-run", "review.started", {})


def test_events_list_runs(tmp_path: Path):
    """list_runs 应返回所有已创建的运行。"""
    from reviewcrew.events import EventStore

    store = EventStore(tmp_path)
    store.create_run()
    store.create_run()

    runs = store.list_runs()
    assert len(runs) == 2
