"""按持久化时间轴回放公开流水线事件。"""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable

from reviewcrew.events import PipelineEvent


Sleep = Callable[[float], Awaitable[None]]


def validate_replay_speed(speed: float) -> float:
    """返回合法回放倍速，并拒绝零、负数及非有限数值。"""

    if not math.isfinite(speed) or speed <= 0:
        raise ValueError("回放速度必须是大于零的有限数值。")
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
