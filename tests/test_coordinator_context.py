from __future__ import annotations

import json
from typing import cast

import pytest
from pydantic_ai.models import Model

from reviewcrew.agents.coordinator import CoordinatorAgent, ReviewPlan
from reviewcrew.models import ContextPack, FileDiff, Hunk


async def test_coordinator_receives_patch_excerpt(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = ""

    class Result:
        output = ReviewPlan.model_validate(
            {
                "summary": "检查挂载边界",
                "missions": [
                    {
                        "id": "mount-risk",
                        "agent": "defect",
                        "objective": "检查宿主机挂载范围",
                        "rationale": "patch 新增共享目录",
                        "context_pack_ids": ["pack"],
                        "focus_files": ["container.py"],
                    }
                ],
            }
        )

    class FakeAgent:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        async def run(self, prompt: str, **kwargs: object) -> Result:
            nonlocal captured
            del kwargs
            captured = prompt
            return Result()

    monkeypatch.setattr("reviewcrew.agents.coordinator.Agent", FakeAgent)
    pack = ContextPack(
        pack_id="pack",
        diff_hunks=[
            FileDiff(
                path="container.py",
                change_type="modify",
                hunks=[
                    Hunk(
                        old_start=1,
                        old_count=0,
                        new_start=1,
                        new_count=1,
                        lines=['+volumes[home_dir] = {"bind": home_dir, "mode": "rw"}'],
                    )
                ],
            )
        ],
    )

    await CoordinatorAgent(model=cast("Model", object())).run([pack])

    payload = json.loads(captured)
    assert "volumes[home_dir]" in payload[0]["patch_excerpt"]
