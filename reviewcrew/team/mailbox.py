"""类型化 Agent Mailbox —— Agent 间异步消息路由、幂等和持久化。

每个运行拥有独立的 Mailbox。第一版使用进程内 asyncio.Queue，
同时将消息追加保存到 runs/{run_id}/mailbox.jsonl。
接口保持可替换，后续可切换 Redis Streams 而不修改 Agent 实现。
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from ..schemas import TeamMessage


class Mailbox:
    """类型化 Agent 消息邮箱。

    规则：
    - 每个 Agent 只有自己的收件队列和共享广播订阅
    - 消息必须有唯一 ID，重复消息按 ID 幂等处理
    - 过期消息不得投递
    - 消息持久化到 JSONL
    """

    def __init__(self, base_dir: str | Path) -> None:
        """初始化 Mailbox。

        Args:
            base_dir: 运行记录的根目录
        """
        self._base_dir = Path(base_dir)
        self._queues: dict[str, asyncio.Queue[TeamMessage]] = defaultdict(asyncio.Queue)
        self._roles: set[str] = set()  # 已知角色（用于广播）
        self._delivered_ids: dict[str, set[str]] = defaultdict(set)  # role -> 已投递消息 ID
        self._correlations: dict[str, str] = {}
        self._active = False
        self._run_id: str | None = None

    # ---- 生命周期 ----

    async def start(self, run_id: str = "default") -> None:
        """启动 Mailbox。"""
        self._active = True
        self._run_id = run_id

    async def close(self) -> None:
        """关闭 Mailbox，不再接受新消息。"""
        self._active = False

    def register(self, role: str) -> None:
        """注册一个角色，使其能接收广播消息。"""
        self._roles.add(role)
        _ = self._queues[role]  # 确保队列存在

    # ---- 消息发布 ----

    async def publish(self, message: TeamMessage) -> None:
        """发布消息到 Mailbox。

        私信投递到指定收件人，广播消息（recipient="*"）投递给所有已知队列。
        """
        if not self._active:
            return

        self._persist(message)

        if message.recipient == "*":
            for role in self._roles:
                await self._queues[role].put(message)
        else:
            await self._queues[message.recipient].put(message)

    # ---- 消息接收 ----

    async def receive_one(
        self, role: str, timeout: float = 5.0
    ) -> TeamMessage | None:
        """接收一条有效消息，支持超时。

        自动跳过过期和重复消息。超时返回 None。

        Args:
            role: 接收方角色名称
            timeout: 等待超时秒数

        Returns:
            有效的 TeamMessage，超时则返回 None
        """
        queue = self._queues[role]
        deadline = datetime.now(timezone.utc)

        while self._active:
            try:
                remaining = timeout - (datetime.now(timezone.utc) - deadline).total_seconds()
                if remaining <= 0:
                    return None
                message = await asyncio.wait_for(queue.get(), timeout=min(remaining, 0.5))
            except asyncio.TimeoutError:
                continue

            # 跳过过期消息
            if message.expires_at and message.expires_at < datetime.now(timezone.utc):
                continue

            # 幂等
            if message.id in self._delivered_ids[role]:
                continue

            self._delivered_ids[role].add(message.id)

            if message.correlation_id:
                self._correlations[message.id] = message.correlation_id

            return message

        return None

    async def receive(self, role: str) -> AsyncIterator[TeamMessage]:
        """异步迭代接收指定角色的消息（用于长时间运行的 Agent）。

        Args:
            role: 接收方角色名称

        Yields:
            有效的 TeamMessage。Mailbox 关闭后停止迭代。
        """
        queue = self._queues[role]
        while self._active:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            if message.expires_at and message.expires_at < datetime.now(timezone.utc):
                continue

            if message.id in self._delivered_ids:
                continue

            self._delivered_ids.add(message.id)

            if message.correlation_id:
                self._correlations[message.id] = message.correlation_id

            yield message

    # ---- 幂等与关联追踪 ----

    def delivered_count(self, message_id: str, role: str = "") -> int:
        """查询某消息 ID 在指定角色的投递次数（0 或 1）。

        不指定 role 时查询所有角色。
        """
        if role:
            return 1 if message_id in self._delivered_ids[role] else 0
        return sum(1 for ids in self._delivered_ids.values() if message_id in ids)

    def get_correlation(self, message_id: str) -> str | None:
        """查询消息的 correlation_id。"""
        return self._correlations.get(message_id)

    # ---- 持久化 ----

    def _persist(self, message: TeamMessage) -> None:
        """将消息追加到 mailbox.jsonl。"""
        if self._run_id is None:
            return

        run_dir = self._base_dir / self._run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        mailbox_file = run_dir / "mailbox.jsonl"

        with open(mailbox_file, "a", encoding="utf-8") as f:
            f.write(message.model_dump_json() + "\n")
            f.flush()
            os.fsync(f.fileno())
