"""根据 PR 规模分配审查时间，并维护共享的绝对截止时间。"""

from __future__ import annotations

import time
from dataclasses import dataclass

from reviewcrew.config import Config
from reviewcrew.schemas import PRData


@dataclass(frozen=True, slots=True)
class ReviewBudget:
    """一次审查的软预算与不可延展的硬截止时间。"""

    team_soft_seconds: int
    hard_seconds: int
    deadline_monotonic: float

    @classmethod
    def from_pr(
        cls,
        pr: PRData,
        config: Config,
        *,
        deadline_monotonic: float | None = None,
    ) -> "ReviewBudget":
        """按文件数和增删行数分级，并将硬上限限制在十分钟内。"""

        file_count = len(pr.files)
        changed_lines = sum(item.additions + item.deletions for item in pr.files)
        if 1 <= file_count <= 3 and changed_lines <= 300:
            team_soft_seconds = 240
        elif 4 <= file_count <= 10 or changed_lines <= 1500:
            team_soft_seconds = 420
        else:
            team_soft_seconds = 600
        hard_seconds = min(config.global_timeout_seconds, 600)
        return cls(
            team_soft_seconds=min(team_soft_seconds, hard_seconds),
            hard_seconds=hard_seconds,
            deadline_monotonic=(
                time.monotonic() + hard_seconds
                if deadline_monotonic is None
                else deadline_monotonic
            ),
        )

    def remaining_seconds(self, *, reserve_seconds: float = 0.0) -> float:
        """返回扣除指定保留时间后的剩余秒数，绝不返回负值。"""

        return max(0.0, self.deadline_monotonic - time.monotonic() - reserve_seconds)
