"""提供审查事件的持久化、订阅和回放基础能力。"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


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
        """创建运行目录并返回不可预测的运行标识。"""

        run_id = f"run-{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
        self._run_dir(run_id).mkdir(parents=True, exist_ok=False)
        return run_id

    def emit(self, run_id: str, event_type: EventType, data: dict[str, Any]) -> PipelineEvent:
        """持久化事件并通知当前订阅者。"""

        with self._lock:
            self._sequences[run_id] += 1
            event = PipelineEvent(
                id=f"evt-{uuid4().hex}",
                run_id=run_id,
                sequence=self._sequences[run_id],
                timestamp=datetime.now(UTC),
                type=event_type,
                data=data,
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

