"""按持久化时间轴回放公开流水线事件。"""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable

from reviewcrew.events import PipelineEvent


Sleep = Callable[[float], Awaitable[None]]
SUPPORTED_REPLAY_SPEEDS = frozenset({0.5, 1.0, 2.0, 4.0, 8.0})


def validate_replay_speed(speed: float) -> float:
    """返回固定档位的合法回放倍速，并拒绝其余数值。"""

    if not math.isfinite(speed) or speed not in SUPPORTED_REPLAY_SPEEDS:
        raise ValueError("回放速度仅支持 0.5、1、2、4、8 倍。")
    return speed


async def replay_events(
    events: Iterable[PipelineEvent],
    *,
    speed: float = 1.0,
    sleep: Sleep = asyncio.sleep,
) -> AsyncIterator[PipelineEvent]:
    """按时间戳和序号稳定回放事件，等待函数可在离线测试中注入。"""

    effective_speed = validate_replay_speed(speed)
    ordered = sorted(events, key=lambda event: (event.timestamp, event.sequence))
    previous: PipelineEvent | None = None
    for event in ordered:
        if previous is not None:
            interval = max(0.0, (event.timestamp - previous.timestamp).total_seconds())
            await sleep(interval / effective_speed)
        yield event
        previous = event
