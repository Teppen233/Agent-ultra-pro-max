"""Agent 基类 —— Pydantic AI 公共运行时和协议定义。

所有 Agent 共享此基类，提供：
- 模型初始化
- 工具访问
- 结构化输出
- Mailbox 通信
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from ..schemas import Finding, ContextPack, AgentSnapshot
from ..team.mailbox import Mailbox
from ..team.blackboard import EvidenceBlackboard

logger = logging.getLogger(__name__)


class ReviewAgentProtocol(Protocol):
    """专家 Agent 协议 —— DefectAgent 和 IntentAgent 的公共接口。"""

    role: str

    async def run(
        self,
        context: ContextPack,
        mailbox: Mailbox,
        blackboard: EvidenceBlackboard,
    ) -> AgentSnapshot:
        """运行审查，产出候选 Finding 并发布到 Mailbox。"""
        ...


class VerifierProtocol(Protocol):
    """Verifier Agent 协议。"""

    role: str

    async def run(
        self,
        mailbox: Mailbox,
        blackboard: EvidenceBlackboard,
    ) -> AgentSnapshot:
        """监听 Mailbox，验证候选 Finding，产出 Verdict。"""
        ...


class AgentRuntime:
    """Agent 运行时 —— 管理 Agent 生命周期、工具和模型调用。"""

    def __init__(self, model: Any) -> None:
        """初始化运行时。

        Args:
            model: Pydantic AI Model 实例（真实或 Fake）
        """
        self.model = model
        self.tool_calls_count = 0

    def log_tool_call(self, tool_name: str) -> None:
        """记录工具调用（用于指标和预算追踪）。"""
        self.tool_calls_count += 1
        logger.debug("工具调用 #%d: %s", self.tool_calls_count, tool_name)

    def make_snapshot(
        self,
        agent_id: str,
        role: str,
        status: str,
        findings_count: int = 0,
    ) -> AgentSnapshot:
        """创建 Agent 状态快照。

        Args:
            agent_id: Agent 唯一标识
            role: Agent 角色
            status: 状态（running, completed, failed, cancelled）
            findings_count: 已产生的候选数量

        Returns:
            AgentSnapshot 实例
        """
        return AgentSnapshot(
            agent_id=agent_id,
            role=role,
            status=status,
            findings_count=findings_count,
            tool_calls_count=self.tool_calls_count,
        )
