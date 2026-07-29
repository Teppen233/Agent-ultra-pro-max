"""Defect 专家 Agent。"""

from __future__ import annotations

from typing import Any

from pydantic_ai.models import Model

from reviewcrew.agents._expert import ExpertAgent
from reviewcrew.agents.base import AgentRuntime, ReviewAgentProtocol
from reviewcrew.config import Config


class DefectAgent(ExpertAgent, ReviewAgentProtocol):
    """聚焦静态破坏、安全、内存与资源生命周期的缺陷专家。"""

    def __init__(
        self,
        model: Model | None = None,
        *,
        skills_root=None,
        config: Config | None = None,
        runtime: AgentRuntime | None = None,
        tools: tuple[Any, ...] = (),
    ) -> None:
        super().__init__(
            role="defect",
            model=model,
            skills_root=skills_root,
            config=config,
            runtime=runtime,
            tools=tools,
        )

    def _checks(self) -> list[str]:
        """返回 Defect 专家的稳定检查范围。"""

        return ["静态破坏", "安全输入", "内存与资源生命周期"]
