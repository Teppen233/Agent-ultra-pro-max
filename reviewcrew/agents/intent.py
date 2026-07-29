"""Intent 专家 Agent。"""

from __future__ import annotations

from typing import Any

from pydantic_ai.models import Model

from reviewcrew.agents._expert import ExpertAgent
from reviewcrew.agents.base import AgentRuntime, ReviewAgentProtocol
from reviewcrew.config import Config


class IntentAgent(ExpertAgent, ReviewAgentProtocol):
    """聚焦需求意图、实际行为、边界条件与架构契约的专家。"""

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
            role="intent",
            model=model,
            skills_root=skills_root,
            config=config,
            runtime=runtime,
            tools=tools,
        )

    def _checks(self) -> list[str]:
        """返回 Intent 专家的稳定检查范围。"""

        return ["意图与行为偏差", "边界条件", "架构契约"]
