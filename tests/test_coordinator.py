from __future__ import annotations

import pytest

from reviewcrew.agents.coordinator import ReviewMission, ReviewPlan, fallback_plan
from reviewcrew.models import ContextPack, FileDiff


def context_pack() -> ContextPack:
    return ContextPack(
        pack_id="auth",
        diff_hunks=[FileDiff(path="src/auth.py", change_type="modify", hunks=[])],
    )


def test_fallback_plan_dispatches_both_experts() -> None:
    plan = fallback_plan([context_pack()])
    assert {mission.agent for mission in plan.missions} == {"defect", "intent"}
    assert all(mission.context_pack_ids == ["auth"] for mission in plan.missions)
    assert all(mission.objective for mission in plan.missions)


def test_plan_rejects_unknown_dependency() -> None:
    with pytest.raises(ValueError, match="dependency"):
        ReviewPlan(
            summary="计划",
            missions=[
                ReviewMission(
                    id="one",
                    agent="defect",
                    objective="检查输入边界",
                    rationale="存在外部输入",
                    context_pack_ids=["auth"],
                    depends_on=["missing"],
                )
            ],
        )
