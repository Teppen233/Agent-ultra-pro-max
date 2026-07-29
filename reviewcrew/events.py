"""事件写入、订阅和回放 —— 基于 JSONL 的 PipelineEvent 持久化。

每条事件立即刷新到 runs/{run_id}/events.jsonl，保证前端断线后可恢复。
SSE 和 Replay 读取相同格式的事件流。
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from .schemas import EventType, PipelineEvent

logger = logging.getLogger(__name__)


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
        try:
            with open(events_file, "a", encoding="utf-8") as f:
                f.write(event.model_dump_json() + "\n")
                f.flush()
                os.fsync(f.fileno())  # 确保写入磁盘
        except OSError as e:
            logger.error("无法写入事件文件 %s: %s", events_file, e)
            raise RuntimeError(f"无法写入事件文件 {events_file}: {e}") from e

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
                    try:
                        events.append(PipelineEvent.model_validate_json(line))
                    except ValidationError:
                        logger.warning("跳过损坏的事件行，文件=%s", events_file)
                        continue
        return events

    # ---- 运行查询 ----

    def list_runs(self) -> list[str]:
        """返回所有运行 ID 列表，包括磁盘上持久化的历史运行。"""
        # 扫描磁盘上已持久化的运行目录
        if self._base_dir.exists():
            for entry in self._base_dir.iterdir():
                if entry.is_dir() and (entry / "events.jsonl").exists():
                    run_id = entry.name
                    if run_id not in self._runs:
                        self._runs.add(run_id)
                        # 同步序列号：从事件文件中读取最大序列号
                        try:
                            max_seq = 0
                            with open(entry / "events.jsonl", encoding="utf-8") as f:
                                for line in f:
                                    line = line.strip()
                                    if line:
                                        try:
                                            data = json.loads(line)
                                            seq = data.get("sequence", 0)
                                            if seq > max_seq:
                                                max_seq = seq
                                        except json.JSONDecodeError:
                                            continue
                            self._sequences[run_id] = max_seq
                        except OSError:
                            logger.warning("无法读取运行 %s 的事件文件", run_id)
        return sorted(self._runs)
