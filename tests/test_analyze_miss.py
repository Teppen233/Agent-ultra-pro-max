from __future__ import annotations

from pathlib import Path

from reviewcrew.events import EventLogger
from reviewcrew.models import Finding, PipelineEvent, Verdict
from reviewcrew.tools.analyze_miss import analyze_miss


def test_attributes_verifier_rejection(tmp_path: Path) -> None:
    logger = EventLogger("run-1", tmp_path)
    finding = Finding(
        id="f1",
        category="logic",
        severity="high",
        confidence=0.8,
        file="service.py",
        line_start=10,
        line_end=11,
        title="State transition is skipped",
        reasoning="The new branch bypasses the transition.",
        trigger_path="handler -> service",
        suggestion="Restore the transition.",
    )
    logger.emit(PipelineEvent(timestamp=1, type="finding", finding=finding))
    logger.emit(
        PipelineEvent(
            timestamp=2,
            type="verdict",
            verdict=Verdict(
                finding_id="f1",
                verdict="reject",
                reason="Not reachable",
                confidence_adjusted=0.2,
            ),
        )
    )

    analysis = analyze_miss("run-1", "state transition bug", tmp_path)

    assert analysis.attribution == "verifier_reject"
