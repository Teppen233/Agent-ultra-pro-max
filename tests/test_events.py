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

