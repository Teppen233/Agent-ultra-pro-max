from __future__ import annotations

from pathlib import Path

from pydantic_ai.models import Model

from reviewcrew.agents.base import ReviewAgent
from reviewcrew.events import EventLogger


class DefectAgent(ReviewAgent):
    def __init__(self, model: Model | None = None, event_logger: EventLogger | None = None) -> None:
        prompt = Path(__file__).parent / "prompts" / "defect.md"
        super().__init__("defect", prompt.read_text(encoding="utf-8"), model, event_logger)
