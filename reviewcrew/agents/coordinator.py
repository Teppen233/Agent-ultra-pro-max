from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_ai import Agent, UnexpectedModelBehavior
from pydantic_ai.models import Model

from reviewcrew.llm.glm import (
    build_glm_model,
    build_model_settings,
    retry_unexpected_model_behavior,
    unlimited_usage,
)
from reviewcrew.models import ContextPack


class ReviewMission(BaseModel):
    id: str
    agent: Literal["defect", "intent"]
    objective: str
    rationale: str
    context_pack_ids: list[str] = Field(min_length=1)
    focus_files: list[str] = Field(default_factory=list)
    priority: int = Field(default=50, ge=1, le=100)
    depends_on: list[str] = Field(default_factory=list)


class ReviewPlan(BaseModel):
    summary: str
    missions: list[ReviewMission] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_dependencies(self) -> ReviewPlan:
        identifiers = {mission.id for mission in self.missions}
        if len(identifiers) != len(self.missions):
            raise ValueError("mission IDs must be unique")
        for mission in self.missions:
            if mission.id in mission.depends_on or not set(mission.depends_on) <= identifiers:
                raise ValueError("mission dependency is invalid")
        return self


def fallback_plan(packs: list[ContextPack], reason: str = "协调模型不可用") -> ReviewPlan:
    missions: list[ReviewMission] = []
    for index, pack in enumerate(packs, 1):
        files = sorted({diff.path for diff in pack.diff_hunks})
        missions.extend(
            [
                ReviewMission(
                    id=f"defect-{index}",
                    agent="defect",
                    objective=f"检查 {', '.join(files) or pack.pack_id} 的安全、资源与静态缺陷",
                    rationale="确定性降级任务，保证缺陷视角不缺席。",
                    context_pack_ids=[pack.pack_id],
                    focus_files=files,
                    priority=80,
                ),
                ReviewMission(
                    id=f"intent-{index}",
                    agent="intent",
                    objective=(
                        f"核对 {', '.join(files) or pack.pack_id} "
                        "的变更意图、业务约束与架构影响"
                    ),
                    rationale="确定性降级任务，保证意图视角不缺席。",
                    context_pack_ids=[pack.pack_id],
                    focus_files=files,
                    priority=70,
                ),
            ]
        )
    if not missions:
        raise ValueError("cannot plan a review without context packs")
    return ReviewPlan(summary=f"{reason}，已生成双专家降级计划。", missions=missions)


class CoordinatorAgent:
    def __init__(self, model: Model | None = None) -> None:
        self.model = model
        prompt = Path(__file__).parent / "prompts" / "coordinator.md"
        self.system_prompt = prompt.read_text(encoding="utf-8")

    async def run(self, packs: list[ContextPack], timeout_seconds: float = 45) -> ReviewPlan:
        compact = [
            {
                "pack_id": pack.pack_id,
                "files": [diff.path for diff in pack.diff_hunks],
                "patch_excerpt": "\n".join(
                    line
                    for diff in pack.diff_hunks
                    for hunk in diff.hunks
                    for line in hunk.lines
                )[:6000],
                "intent": pack.intent[:2000],
                "architecture": pack.arch_summary[:1200],
                "signals": [signal.model_dump() for signal in pack.static_signals[:20]],
            }
            for pack in packs
        ]
        try:
            async with asyncio.timeout(timeout_seconds):
                agent = Agent(
                    self.model or build_glm_model(),
                    output_type=ReviewPlan,
                    system_prompt=self.system_prompt,
                    model_settings=build_model_settings(0.1),
                    retries=3,
                )
                result = await retry_unexpected_model_behavior(
                    lambda: agent.run(
                        json.dumps(compact, ensure_ascii=True),
                        usage_limits=unlimited_usage(),
                    )
                )
                known_packs = {pack.pack_id for pack in packs}
                if any(
                    not set(mission.context_pack_ids) <= known_packs
                    for mission in result.output.missions
                ):
                    return fallback_plan(packs, "协调计划引用了未知上下文")
                return result.output
        except (TimeoutError, ExceptionGroup, ValueError, UnexpectedModelBehavior):
            return fallback_plan(packs)
