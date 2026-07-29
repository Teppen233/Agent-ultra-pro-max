"""事件回放模块 —— 按指定速度回放历史 PipelineEvent。

SSE 和 Replay 输出相同的事件格式，前端不需要维护两套逻辑。
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from ..schemas import PipelineEvent


async def replay_events(
    events: list[PipelineEvent],
    speed: float = 1.0,
) -> AsyncIterator[PipelineEvent]:
    """按原始时间间隔回放事件（异步，不阻塞事件循环）。

    Args:
        events: 按时间排序的事件列表
        speed: 回放速度倍率（1.0=原速, 2.0=两倍速, 0.5=半速）

    Yields:
        PipelineEvent，按调整后的间隔依次产出
    """
    if not events:
        return

    prev_time = events[0].timestamp
    for event in events:
        # 计算与上一事件的真实间隔
        delta = (event.timestamp - prev_time).total_seconds()
        if delta > 0 and speed > 0:
            await asyncio.sleep(delta / speed)
        prev_time = event.timestamp
        yield event
