"""VerifierAgent —— 候选 Finding 独立验证专家。

不主动寻找新问题，只验证候选 Finding：
1. 是否由当前 PR 引入
2. 是否定位到修改行
3. 触发路径是否可达
4. 是否存在上游保护
5. 是否与其他 Finding 重复
6. 严重度和置信度是否合理
7. 证据是否足以发布
"""

from __future__ import annotations

import logging
from typing import Any

from ..schemas import AgentSnapshot
from ..team.mailbox import Mailbox
from ..team.blackboard import EvidenceBlackboard
from .base import AgentRuntime

logger = logging.getLogger(__name__)


class VerifierAgent(AgentRuntime):
    """验证 Agent —— 独立验证和过滤候选 Finding。"""

    role = "verifier"

    def __init__(self, model: Any, agent_id: str = "verifier-1") -> None:
        super().__init__(model)
        self.agent_id = agent_id

    async def run(
        self,
        mailbox: Mailbox | None = None,
        blackboard: EvidenceBlackboard | None = None,
    ) -> AgentSnapshot:
        """监听 Mailbox，验证候选 Finding。

        Verifier watcher 在第一个候选到达时被 Orchestrator 唤醒。
        对每个候选独立验证并输出 Verdict。

        Args:
            mailbox: Agent 消息邮箱
            blackboard: 共享证据黑板

        Returns:
            Agent 状态快照
        """
        logger.info("VerifierAgent[%s] 开始验证候选 Finding", self.agent_id)

        # TODO: 从 Mailbox 读取候选，逐一验证并产出 Verdict
        return self.make_snapshot(
            agent_id=self.agent_id,
            role=self.role,
            status="completed",
            findings_count=0,
        )
