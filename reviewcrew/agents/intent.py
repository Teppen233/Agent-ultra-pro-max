from __future__ import annotations

from pathlib import Path

from pydantic_ai.models import Model

from reviewcrew.agents.base import ReviewAgent
from reviewcrew.events import EventLogger
from reviewcrew.models import ContextPack


def shard_packs(packs: list[ContextPack], max_shards: int = 3) -> list[list[ContextPack]]:
    if not packs:
        return []
    count = min(max_shards, len(packs))
    shards: list[list[ContextPack]] = [[] for _ in range(count)]
    for index, pack in enumerate(packs):
        shards[index % count].append(pack)
    return shards


class IntentAgent(ReviewAgent):
    def __init__(self, model: Model | None = None, event_logger: EventLogger | None = None) -> None:
        prompt = Path(__file__).parent / "prompts" / "intent.md"
        super().__init__("intent", prompt.read_text(encoding="utf-8"), model, event_logger)
