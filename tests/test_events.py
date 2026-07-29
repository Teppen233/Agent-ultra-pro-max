"""事件存储和订阅测试。"""

import asyncio

import pytest

from reviewcrew.events import EventStore


def test_events_receive_monotonic_sequence(tmp_path) -> None:
    """同一运行的事件序号必须严格递增并可重新读取。"""

    store = EventStore(tmp_path)
    run_id = store.create_run()

    first = store.emit(run_id, "review.started", {})
    second = store.emit(run_id, "stage.started", {"stage": "loading_pr"})

    assert [first.sequence, second.sequence] == [1, 2]
    assert store.read(run_id) == [first, second]


def test_reserved_run_can_be_claimed_once_and_rejects_duplicate_or_dirty_directory(tmp_path) -> None:
    """预留目录只能原子 claim 一次，重复和非预留目录必须中文拒绝。"""

    store = EventStore(tmp_path)
    reserved = store.create_run()
    store.claim_run(reserved)
    with pytest.raises(RuntimeError, match="运行.*已"):
        store.claim_run(reserved)

    dirty = "run-dirty"
    dirty_dir = tmp_path / dirty
    dirty_dir.mkdir()
    (dirty_dir / "result.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="预留"):
        store.claim_run(dirty)


def test_new_event_store_continues_existing_sequence_without_reset(tmp_path) -> None:
    """同一已 claim 运行由新 EventStore 追加事件时序号继续递增。"""

    first_store = EventStore(tmp_path)
    run_id = first_store.create_run()
    first = first_store.emit(run_id, "review.started", {})
    second_store = EventStore(tmp_path)
    second = second_store.emit(run_id, "review.completed", {"status": "completed"})

    assert first.sequence == 1
    assert second.sequence == 2


@pytest.mark.asyncio
async def test_subscriber_receives_new_event(tmp_path) -> None:
    """订阅者应收到订阅后产生的新事件。"""

    store = EventStore(tmp_path)
    run_id = store.create_run()
    iterator = store.subscribe(run_id)
    pending = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0)

    emitted = store.emit(run_id, "agent.started", {"agent": "defect"})

    assert await asyncio.wait_for(pending, timeout=1) == emitted
