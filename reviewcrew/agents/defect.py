"""DefectAgent —— 模式匹配和证据驱动的缺陷审查专家。

负责发现：
- 静态缺陷：语法、类型、导入、依赖问题
- 安全漏洞：注入、SSRF、路径穿越、越权
- 内存与资源：泄漏、无界集合、未等待异步任务

只能输出候选 Finding，不得绕过 Verifier 发布结论。
"""

from __future__ import annotations

import logging
from typing import Any

from ..schemas import ContextPack, AgentSnapshot
from ..team.mailbox import Mailbox
from ..team.blackboard import EvidenceBlackboard
from .base import AgentRuntime

logger = logging.getLogger(__name__)


class DefectAgent(AgentRuntime):
    """缺陷审查 Agent —— 技术缺陷发现专家。"""

    role = "defect"

    def __init__(self, model: Any, agent_id: str = "defect-1") -> None:
        super().__init__(model)
        self.agent_id = agent_id

    async def run(
        self,
        context: ContextPack,
        mailbox: Mailbox | None = None,
        blackboard: EvidenceBlackboard | None = None,
    ) -> AgentSnapshot:
        """对 ContextPack 进行缺陷审查。

        使用 Fake Model 时返回空候选列表；真实模型时收集证据并产出 Finding。

        Args:
            context: 审查上下文包
            mailbox: Agent 消息邮箱（可选）
            blackboard: 共享证据黑板（可选）

        Returns:
            Agent 状态快照
        """
        logger.info(
            "DefectAgent[%s] 开始审查 %d 个文件",
            self.agent_id,
            len(context.files),
        )

        # TODO: 使用 Pydantic AI Agent 进行真实的 LLM 调用
        # 当前返回基线快照
        return self.make_snapshot(
            agent_id=self.agent_id,
            role=self.role,
            status="completed",
            findings_count=0,
        )
