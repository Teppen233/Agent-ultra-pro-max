from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from reviewcrew.models import PipelineEvent

EventSubscriber = Callable[[PipelineEvent], None]


class EventLogger:
    def __init__(self, run_id: str, output_dir: Path = Path("runs")) -> None:
        self.run_id = run_id
        self.run_dir = output_dir / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / "events.jsonl"
        self._lock = threading.Lock()
        self._subscribers: list[EventSubscriber] = []

    def subscribe(self, callback: EventSubscriber) -> Callable[[], None]:
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    def emit(self, event: PipelineEvent) -> None:
        line = event.model_dump_json(exclude_none=True) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(line)
        for subscriber in tuple(self._subscribers):
            subscriber(event)
