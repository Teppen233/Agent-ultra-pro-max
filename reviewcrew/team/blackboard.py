"""保存 Agent Team 可以共享的结构化事实。"""

from __future__ import annotations

from dataclasses import dataclass, field

from reviewcrew.schemas import TeamMessage


@dataclass(slots=True)
class EvidenceBlackboard:
    """只保存结构化消息，不保存模型隐藏思维链。"""

    run_id: str
    messages: list[TeamMessage] = field(default_factory=list)
    _message_ids: set[str] = field(default_factory=set, init=False, repr=False)

    def apply(self, message: TeamMessage) -> None:
        """幂等地应用一条团队消息。"""

        if message.run_id != self.run_id:
            raise ValueError("消息运行标识与共享黑板不一致")
        if message.id in self._message_ids:
            return
        self._message_ids.add(message.id)
        self.messages.append(message)

    def by_kind(self, kind: str) -> list[TeamMessage]:
        """按消息类型查询共享事实。"""

        return [message for message in self.messages if message.kind == kind]

