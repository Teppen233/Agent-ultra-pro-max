"""为团队消息提供可注入的原子发布桥接。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from reviewcrew.redaction import sanitize_persisted_value
from reviewcrew.schemas import TeamMessage
from reviewcrew.team.blackboard import EvidenceBlackboard
from reviewcrew.team.mailbox import Mailbox


class SequenceAllocator:
    """在单个运行内原子分配连续序号。"""

    def __init__(self, initial: int = 0) -> None:
        self._next = initial
        self._lock = asyncio.Lock()

    async def allocate(self) -> int:
        """返回下一个唯一序号。"""

        async with self._lock:
            self._next += 1
            return self._next


class MessagePublisher:
    """统一分配序号并同步写入 Mailbox 与 Blackboard。"""

    def __init__(self, *, mailbox: Mailbox | None, blackboard: EvidenceBlackboard | None, allocator: SequenceAllocator | None = None) -> None:
        if mailbox is None and blackboard is None:
            raise ValueError("发布桥接至少需要一个协作设施")
        run_id = blackboard.run_id if blackboard is not None else mailbox.run_id  # type: ignore[union-attr]
        if mailbox is not None and mailbox.run_id != run_id:
            raise ValueError("Mailbox 与 Blackboard 的运行标识不一致")
        initial = max((item.sequence for item in blackboard.messages), default=0) if blackboard is not None else 0
        self.run_id = run_id
        self.mailbox = mailbox
        self.blackboard = blackboard
        if allocator is not None:
            self.allocator = allocator
        else:
            self.allocator = self._allocators.setdefault(run_id, SequenceAllocator(initial))

    async def publish(
        self,
        *,
        sender: str,
        recipient: str,
        kind: str,
        key: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> bool:
        """以单一分配点构造、投递并记录一条安全结构化消息。"""

        message = TeamMessage(
            id=f"{sender}:{key}", run_id=self.run_id, sequence=await self.allocator.allocate(), timestamp=datetime.now(UTC),
            sender=sender,
            recipient=recipient,
            kind=kind,
            correlation_id=correlation_id,
            expires_at=expires_at,
            payload=payload,
        )
        persisted_message = message.model_copy(
            update={"payload": sanitize_persisted_value(message.payload)}
        )
        if self.mailbox is not None and not await self.mailbox.publish(
            message,
            persisted_message=persisted_message,
        ):
            return False
        if self.blackboard is not None:
            self.blackboard.apply(message)
        return True
    _allocators: dict[str, SequenceAllocator] = {}
