from __future__ import annotations

import json
import time
from pathlib import Path

from reviewcrew.events import EventLogger
from reviewcrew.models import PipelineEvent, WorkflowNode


def test_event_roundtrip() -> None:
    event = PipelineEvent(timestamp=time.time(), type="stage", stage="preprocess", status="start")
    assert PipelineEvent.model_validate_json(event.model_dump_json()) == event


def test_event_logger_writes_jsonl(tmp_path: Path) -> None:
    logger = EventLogger(run_id="test123", output_dir=tmp_path)
    seen: list[PipelineEvent] = []
    logger.subscribe(seen.append)
    event = PipelineEvent(timestamp=1.0, type="thought", agent="defect", text="inspect")
    logger.emit(event)
    lines = logger.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["text"] == "inspect"
    assert seen == [event]


def test_workflow_event_roundtrip() -> None:
    node = WorkflowNode(
        id="task-1",
        kind="agent_task",
        label="检查认证边界",
        agent="defect",
        status="queued",
    )
    event = PipelineEvent(timestamp=1, type="workflow_node", workflow_node=node)
    assert PipelineEvent.model_validate_json(event.model_dump_json()) == event
