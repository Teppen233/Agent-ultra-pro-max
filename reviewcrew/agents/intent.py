"""IntentAgent —— 语义理解和意图对齐型缺陷审查专家。

负责发现：
- 业务逻辑：需求、测试和实现行为不一致
- 普通逻辑：边界条件、条件组合、状态转换
- 架构问题：模块依赖方向、跨层调用、接口破坏

使用固定流程：先总结作者意图，再总结实际行为，最后比较两者。
"""

from __future__ import annotations

import logging
from typing import Any

from ..schemas import ContextPack, AgentSnapshot
from ..team.mailbox import Mailbox
from ..team.blackboard import EvidenceBlackboard
from .base import AgentRuntime

logger = logging.getLogger(__name__)


class IntentAgent(AgentRuntime):
    """意图审查 Agent —— 语义和逻辑发现专家。"""

    role = "intent"

    def __init__(self, model: Any, agent_id: str = "intent-1") -> None:
        super().__init__(model)
        self.agent_id = agent_id

    async def run(
        self,
        context: ContextPack,
        mailbox: Mailbox | None = None,
        blackboard: EvidenceBlackboard | None = None,
    ) -> AgentSnapshot:
        """对 ContextPack 进行意图和逻辑审查。

        Args:
            context: 审查上下文包
            mailbox: Agent 消息邮箱（可选）
            blackboard: 共享证据黑板（可选）

        Returns:
            Agent 状态快照
        """
        logger.info(
            "IntentAgent[%s] 开始审查 PR: %s",
            self.agent_id,
            context.pr_title,
        )

        # TODO: 使用 Pydantic AI Agent 进行真实 LLM 调用
        return self.make_snapshot(
            agent_id=self.agent_id,
            role=self.role,
            status="completed",
            findings_count=0,
        )
