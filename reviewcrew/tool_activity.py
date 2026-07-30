"""统一发布可公开、可回放的真实工具活动。"""

from __future__ import annotations

import time
from dataclasses import dataclass

from reviewcrew.events import EventStore
from reviewcrew.schemas import ToolActorType


_ACTOR_LIMIT = 120
_TOOL_NAME_LIMIT = 120
_TARGET_LIMIT = 240
_SUMMARY_LIMIT = 500
_CONTEXT_LIMIT = 120
_AGENT_LIMIT = 160


class ToolActivityPublisher:
    """为单次运行创建工具开始、完成、失败和降级事件。"""

    def __init__(self, store: EventStore, run_id: str) -> None:
        self.store = store
        self.run_id = run_id

    def started(
        self,
        *,
        actor: str,
        actor_type: ToolActorType,
        tool_name: str,
        target: str = "",
        summary: str = "",
        context_id: str | None = None,
        agent_id: str | None = None,
    ) -> "ToolActivityHandle":
        """仅在调用方即将执行真实动作时发布开始事件。"""

        activity = _ToolActivity(
            actor=_clip(actor, _ACTOR_LIMIT),
            actor_type=actor_type,
            tool_name=_clip(tool_name, _TOOL_NAME_LIMIT),
            target=_clip(target, _TARGET_LIMIT),
            context_id=_clip_optional(context_id, _CONTEXT_LIMIT),
            agent_id=_clip_optional(agent_id, _AGENT_LIMIT),
        )
        self.store.emit(
            self.run_id,
            "tool.started",
            activity.data(summary=_clip(summary, _SUMMARY_LIMIT), duration_ms=0),
        )
        return ToolActivityHandle(self, activity, time.perf_counter())

    def degraded(
        self,
        *,
        actor: str,
        actor_type: ToolActorType,
        tool_name: str,
        target: str,
        summary: str,
        context_id: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        """记录未执行能力的明确降级，不伪造开始或成功事件。"""

        activity = _ToolActivity(
            actor=_clip(actor, _ACTOR_LIMIT),
            actor_type=actor_type,
            tool_name=_clip(tool_name, _TOOL_NAME_LIMIT),
            target=_clip(target, _TARGET_LIMIT),
            context_id=_clip_optional(context_id, _CONTEXT_LIMIT),
            agent_id=_clip_optional(agent_id, _AGENT_LIMIT),
        )
        self.store.emit(
            self.run_id,
            "tool.failed",
            activity.data(summary=_clip(summary, _SUMMARY_LIMIT), duration_ms=0),
        )


@dataclass(slots=True)
class ToolActivityHandle:
    """跟踪一次已开始动作，并保证只发布一个终态。"""

    publisher: ToolActivityPublisher
    activity: "_ToolActivity"
    started_at: float
    _finished: bool = False

    def complete(self, summary: str, result_count: int | None = None) -> None:
        """真实动作成功返回后发布完成摘要。"""

        self._finish("tool.completed", summary, result_count)

    def fail(self, summary: str) -> None:
        """真实动作失败后发布安全的中文失败摘要。"""

        self._finish("tool.failed", summary, None)

    def _finish(self, event_type: str, summary: str, result_count: int | None) -> None:
        if self._finished:
            raise RuntimeError("工具活动已经结束，不能重复发布终态")
        self._finished = True
        duration_ms = max(0, round((time.perf_counter() - self.started_at) * 1000))
        self.publisher.store.emit(
            self.publisher.run_id,
            event_type,
            self.activity.data(
                summary=_clip(summary, _SUMMARY_LIMIT),
                duration_ms=duration_ms,
                result_count=result_count,
            ),
        )


@dataclass(frozen=True, slots=True)
class _ToolActivity:
    """保存一次活动在开始和终态之间不变的公开身份。"""

    actor: str
    actor_type: ToolActorType
    tool_name: str
    target: str
    context_id: str | None
    agent_id: str | None

    def data(
        self,
        *,
        summary: str,
        duration_ms: int,
        result_count: int | None = None,
    ) -> dict[str, object]:
        """生成只包含公开白名单字段的事件数据。"""

        return {
            "actor": self.actor,
            "actor_type": self.actor_type,
            "tool_name": self.tool_name,
            "target": self.target,
            "summary": summary,
            "duration_ms": duration_ms,
            "result_count": result_count,
            "context_id": self.context_id,
            "agent_id": self.agent_id,
        }


def _clip(value: str, limit: int) -> str:
    """按公开契约长度裁剪单行字符串。"""

    normalized = " ".join(str(value).split())
    return normalized[:limit]


def _clip_optional(value: str | None, limit: int) -> str | None:
    """裁剪可选公开标识，空白值归一化为未提供。"""

    if value is None:
        return None
    normalized = _clip(value, limit)
    return normalized or None
