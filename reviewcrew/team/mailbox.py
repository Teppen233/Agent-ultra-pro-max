"""实现类型化、可持久化的 Agent Team Mailbox。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from reviewcrew.schemas import TeamMessage


class Mailbox:
    """为每个 Agent 提供私有收件箱和广播消息。

    第一版使用进程内队列，但同时将消息写入 JSONL，便于审计、回放和
    后续替换为 Redis Streams。
    """

    def __init__(self, runs_root: Path, run_id: str) -> None:
        self.run_id = run_id
        self.run_dir = Path(runs_root) / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._queues: dict[str, asyncio.Queue[TeamMessage]] = defaultdict(asyncio.Queue)
        self._published_ids: set[str] = set()
        self._delivered: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    def register(self, agent_id: str) -> None:
        """显式注册一个 Agent 的收件箱。"""

        self._queues[agent_id]

    async def publish(
        self,
        message: TeamMessage,
        *,
        persisted_message: TeamMessage | None = None,
    ) -> bool:
        """发布完整内存消息，并可将独立脱敏副本写入审计文件。"""

        if message.run_id != self.run_id:
            raise ValueError("消息运行标识与 Mailbox 不一致")
        if message.expires_at is not None and message.expires_at <= datetime.now(UTC):
            return False
        audit_message = persisted_message or message
        if audit_message.id != message.id or audit_message.run_id != message.run_id:
            raise ValueError("持久化消息必须与投递消息具有相同标识")

        async with self._lock:
            if message.id in self._published_ids:
                return False
            self._published_ids.add(message.id)
            with (self.run_dir / "mailbox.jsonl").open("a", encoding="utf-8") as file:
                file.write(audit_message.model_dump_json() + "\n")

            if message.recipient == "*":
                recipients = list(self._queues)
            else:
                recipients = [message.recipient]
            for recipient in recipients:
                self._queues[recipient].put_nowait(message)
                self._delivered[message.id] += 1
        return True

    async def receive_one(self, agent_id: str, timeout: float | None = None) -> TeamMessage:
        """读取指定 Agent 的一条消息，并支持超时。"""

        queue = self._queues[agent_id]
        try:
            async with asyncio.timeout(timeout):
                return await queue.get()
        except TimeoutError:
            raise

    def delivered_count(self, message_id: str) -> int:
        """返回一条消息被送入收件队列的次数。"""

        return self._delivered[message_id]
