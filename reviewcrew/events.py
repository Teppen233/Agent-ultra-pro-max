"""事件写入、订阅和回放 —— 基于 JSONL 的 PipelineEvent 持久化。

每条事件立即刷新到 runs/{run_id}/events.jsonl，保证前端断线后可恢复。
SSE 和 Replay 读取相同格式的事件流。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .schemas import EventType, PipelineEvent


class EventStore:
    """事件存储 —— 管理审查运行中的 PipelineEvent 生命周期。

    事件逐条追加到 JSONL 文件，每条一行，即时刷新。
    """

    def __init__(self, base_dir: str | Path) -> None:
        """初始化事件存储。

        Args:
            base_dir: 运行记录的根目录（通常为 Config.runs_dir）
        """
        self._base_dir = Path(base_dir)
        self._sequences: dict[str, int] = {}  # run_id -> 当前序列号
        self._runs: set[str] = set()

    # ---- 运行生命周期 ----

    def create_run(self) -> str:
        """创建新的审查运行并返回 run_id。"""
        run_id = uuid.uuid4().hex[:12]
        run_dir = self._base_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        self._sequences[run_id] = 0
        self._runs.add(run_id)
        return run_id

    # ---- 事件发射 ----

    def emit(
        self,
        run_id: str,
        event_type: EventType,
        data: dict,
    ) -> PipelineEvent:
        """发射一条管道事件并持久化。

        Args:
            run_id: 运行 ID
            event_type: 事件类型
            data: 事件数据字典

        Returns:
            创建并持久化的 PipelineEvent

        Raises:
            ValueError: run_id 不存在
        """
        if run_id not in self._runs:
            raise ValueError(f"运行 {run_id} 不存在，请先调用 create_run()")

        sequence = self._sequences[run_id] + 1
        self._sequences[run_id] = sequence

        event = PipelineEvent(
            id=f"evt-{run_id}-{sequence:04d}",
            run_id=run_id,
            sequence=sequence,
            timestamp=datetime.now(timezone.utc),
            type=event_type,
            data=data,
        )

        # 追加写入 JSONL
        events_file = self._base_dir / run_id / "events.jsonl"
        with open(events_file, "a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")
            f.flush()
            os.fsync(f.fileno())  # 确保写入磁盘

        return event

    # ---- 事件读取 ----

    def read(self, run_id: str) -> list[PipelineEvent]:
        """读取指定运行的全部事件。

        Args:
            run_id: 运行 ID

        Returns:
            按序列号排序的事件列表
        """
        events_file = self._base_dir / run_id / "events.jsonl"
        if not events_file.exists():
            return []

        events: list[PipelineEvent] = []
        with open(events_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(PipelineEvent.model_validate_json(line))
        return events

    # ---- 运行查询 ----

    def list_runs(self) -> list[str]:
        """返回所有已创建的运行 ID 列表。"""
        return sorted(self._runs)
