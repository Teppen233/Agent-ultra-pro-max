"""提供审查事件的持久化、订阅和回放基础能力。"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from reviewcrew.redaction import sanitize_persisted_value
from reviewcrew.schemas import MailboxEventData, PlanPublishedData, ToolActivityData


EventType = Literal[
    "review.started",
    "review.completed",
    "review.failed",
    "stage.started",
    "stage.completed",
    "stage.failed",
    "agent.started",
    "agent.tool",
    "agent.candidate",
    "agent.completed",
    "agent.failed",
    "plan.published",
    "tool.started",
    "tool.completed",
    "tool.degraded",
    "tool.failed",
    "mailbox.message",
    "verifier.started",
    "verifier.accepted",
    "verifier.rejected",
    "verifier.completed",
    "report.generated",
]


class PipelineEvent(BaseModel):
    """前后端共享的审查事件。"""

    id: str
    run_id: str
    sequence: int = Field(ge=1)
    timestamp: datetime
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)


class EventStore:
    """将事件写入 JSONL，并向当前订阅者实时广播。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._sequences: dict[str, int] = defaultdict(int)
        self._subscribers: dict[str, set[asyncio.Queue[PipelineEvent]]] = defaultdict(set)
        self._lock = Lock()

    def create_run(self) -> str:
        """原子创建预留运行目录，等待后台 Orchestrator claim。"""

        run_id = f"run-{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / ".reserved").write_text("reserved\n", encoding="utf-8")
        return run_id

    def claim_run(self, run_id: str) -> None:
        """原子认领一个干净的预留运行；重复或脏目录以中文拒绝。"""

        with self._lock:
            self._claim_run_unlocked(run_id)

    def emit(self, run_id: str, event_type: EventType, data: dict[str, Any]) -> PipelineEvent:
        """持久化事件并通知当前订阅者。"""

        with self._lock:
            run_dir = self._run_dir(run_id)
            if (run_dir / ".reserved").exists():
                self._claim_run_unlocked(run_id)
            if not (run_dir / ".claimed").is_file():
                raise RuntimeError("运行未预留或尚未被认领，无法写入事件")
            if run_id not in self._sequences:
                existing = self.read(run_id)
                self._sequences[run_id] = max((event.sequence for event in existing), default=0)
            self._sequences[run_id] += 1
            event = PipelineEvent(
                id=f"evt-{uuid4().hex}",
                run_id=run_id,
                sequence=self._sequences[run_id],
                timestamp=datetime.now(UTC),
                type=event_type,
                data=_public_event_data(event_type, data),
            )
            run_dir = self._run_dir(run_id)
            run_dir.mkdir(parents=True, exist_ok=True)
            with (run_dir / "events.jsonl").open("a", encoding="utf-8") as file:
                file.write(event.model_dump_json() + "\n")

        for queue in tuple(self._subscribers[run_id]):
            queue.put_nowait(event)
        return event

    def read(self, run_id: str) -> list[PipelineEvent]:
        """读取一次运行已经持久化的全部事件。"""

        path = self._run_dir(run_id) / "events.jsonl"
        if not path.exists():
            return []
        events: list[PipelineEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(PipelineEvent.model_validate(json.loads(line)))
        return events

    async def subscribe(self, run_id: str) -> AsyncIterator[PipelineEvent]:
        """订阅调用之后产生的事件；关闭迭代器时自动注销。"""

        queue: asyncio.Queue[PipelineEvent] = asyncio.Queue()
        self._subscribers[run_id].add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers[run_id].discard(queue)

    def _run_dir(self, run_id: str) -> Path:
        """返回运行目录，并拒绝路径注入。"""

        if not run_id or any(character in run_id for character in ("/", "\\", "..")):
            raise ValueError("运行标识包含非法路径字符")
        return self.root / run_id

    def _claim_run_unlocked(self, run_id: str) -> None:
        run_dir = self._run_dir(run_id)
        reserved = run_dir / ".reserved"
        claimed = run_dir / ".claimed"
        if claimed.exists():
            raise RuntimeError("运行已被认领或已经启动")
        if not run_dir.is_dir() or not reserved.is_file():
            raise RuntimeError("运行目录未经过预留，拒绝启动审查")
        if any(path.name != ".reserved" for path in run_dir.iterdir()):
            raise RuntimeError("预留运行目录已包含数据，拒绝启动审查")
        try:
            os.replace(reserved, claimed)
        except OSError as error:
            raise RuntimeError("运行已被其他审查任务认领") from error


def _public_event_data(event_type: EventType, data: dict[str, Any]) -> dict[str, Any]:
    """按事件类型冻结公开字段，并统一移除敏感结构。"""

    sanitized = sanitize_persisted_value(data)
    if event_type.startswith("tool."):
        status = event_type.removeprefix("tool.")
        clipped = _clip_mapping_strings(
            sanitized,
            {
                "actor": 120,
                "tool_name": 120,
                "target": 240,
                "summary": 500,
                "context_id": 120,
                "agent_id": 160,
            },
        )
        return ToolActivityData.model_validate({**clipped, "status": status}).model_dump(mode="json")
    if event_type == "plan.published":
        clipped = _clip_mapping_strings(sanitized, {"summary": 500})
        return PlanPublishedData.model_validate(clipped).model_dump(mode="json")
    if event_type == "mailbox.message":
        clipped = _clip_mapping_strings(
            sanitized,
            {
                "sender": 160,
                "recipient": 160,
                "correlation_id": 160,
                "summary": 500,
            },
        )
        return MailboxEventData.model_validate(clipped).model_dump(mode="json")
    return _remove_sensitive_keys(sanitized)


def _remove_sensitive_keys(value: Any) -> Any:
    """补充过滤密钥、令牌和授权字段，避免公开事件边界泄漏。"""

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if _is_secret_public_key(key):
                continue
            result[key] = _remove_sensitive_keys(item)
        return result
    if isinstance(value, list):
        return [_remove_sensitive_keys(item) for item in value]
    return value


def _is_secret_public_key(key: str) -> bool:
    """识别密钥、令牌、授权和推理字段的常见命名变体。"""

    normalized = key.casefold()
    tokens = {token for token in re.split(r"[^a-z0-9]+", normalized) if token}
    if normalized in {"authorization", "secret", "password", "reasoning"}:
        return True
    if "token" in tokens or "secret" in tokens or "password" in tokens:
        return True
    if {"api", "key"} <= tokens:
        return True
    return normalized.startswith("reasoning")


def _clip_mapping_strings(data: dict[str, Any], limits: dict[str, int]) -> dict[str, Any]:
    """按公开字段各自上限裁剪字符串，其他字段保持结构化值。"""

    clipped = dict(data)
    for key, limit in limits.items():
        value = clipped.get(key)
        if isinstance(value, str):
            clipped[key] = " ".join(value.split())[:limit]
    return clipped
