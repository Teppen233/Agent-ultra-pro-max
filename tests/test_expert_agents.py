from __future__ import annotations

from reviewcrew.agents.defect import DefectAgent
from reviewcrew.agents.intent import IntentAgent, shard_packs
from reviewcrew.models import ContextPack


def pack(number: int) -> ContextPack:
    return ContextPack(pack_id=f"p{number}", diff_hunks=[])


def test_shard_packs_respects_max() -> None:
    shards = shard_packs([pack(index) for index in range(10)], max_shards=3)
    assert len(shards) == 3
    assert sum(map(len, shards)) == 10


def test_agents_load_prompts_without_api_key() -> None:
    assert "Section 1: Security" in DefectAgent().system_prompt
    assert "Step 1: Summarize Intent" in IntentAgent().system_prompt
