from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from reviewcrew.models import PipelineEvent


def load_events_jsonl(path: Path) -> list[PipelineEvent]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return [
        PipelineEvent.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def tail_events_file(
    path: Path, poll_interval: float = 0.1, idle_timeout: float = 620
) -> AsyncIterator[PipelineEvent]:
    waited = 0.0
    while not path.exists():
        if waited >= idle_timeout:
            return
        await asyncio.sleep(poll_interval)
        waited += poll_interval

    with path.open(encoding="utf-8") as stream:
        idle = 0.0
        while idle < idle_timeout:
            line = stream.readline()
            if not line:
                await asyncio.sleep(poll_interval)
                idle += poll_interval
                continue
            idle = 0.0
            event = PipelineEvent.model_validate_json(line)
            yield event
            if event.type == "report" or (
                event.type == "stage" and event.status == "error"
            ):
                return


async def replay_events(
    events: list[PipelineEvent], speed: float = 1.0
) -> AsyncIterator[PipelineEvent]:
    previous: float | None = None
    for event in events:
        if previous is not None:
            await asyncio.sleep(max(0.0, event.timestamp - previous) / speed)
        yield event
        previous = event.timestamp


def encode_sse(event: PipelineEvent) -> str:
    return f"event: {event.type}\ndata: {event.model_dump_json(exclude_none=True)}\n\n"
