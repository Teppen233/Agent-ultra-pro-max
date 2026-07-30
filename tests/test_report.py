from __future__ import annotations

from reviewcrew.models import Finding
from reviewcrew.pipeline.report import generate_report


def test_report_and_github_comment() -> None:
    finding = Finding(
        category="logic",
        severity="high",
        confidence=0.8,
        file="app.py",
        line_start=12,
        line_end=14,
        title="State is not restored",
        reasoning="The failure branch leaves the state pending.",
        trigger_path="request -> failure",
        suggestion="Restore the previous state in the failure branch.",
        verdict="keep",
        confidence_adjusted=0.8,
    )
    markdown, payload = generate_report([finding])
    assert "State is not restored" in markdown
    assert payload["comments"][0]["path"] == "app.py"
    assert payload["comments"][0]["line"] == 12
    assert "审查摘要" in markdown
    assert "触发路径" in markdown


def test_report_preserves_rejected_candidates_but_not_github_comments() -> None:
    rejected = Finding(
        category="security",
        severity="high",
        confidence=0.95,
        file="auth.py",
        line_start=8,
        line_end=8,
        title="Possible authentication bypass",
        reasoning="A guard may be skipped.",
        trigger_path="request -> guard",
        suggestion="Keep the guard.",
        verdict="reject",
        verdict_reason="Verifier found a conflicting guard.",
        confidence_adjusted=0.1,
    )
    markdown, payload = generate_report([rejected])
    assert "Verifier 已排除的候选" in markdown
    assert "Possible authentication bypass" in markdown
    assert "Verifier found a conflicting guard" in markdown
    assert payload["comments"] == []


def test_report_does_not_replace_zero_adjusted_confidence_with_original() -> None:
    rejected = Finding(
        category="logic",
        severity="high",
        confidence=0.95,
        file="auth.py",
        line_start=9,
        line_end=9,
        title="Disproved candidate",
        reasoning="The original hypothesis.",
        trigger_path="request -> branch",
        suggestion="No change after verification.",
        verdict="reject",
        verdict_reason="The path is unreachable.",
        confidence_adjusted=0.0,
    )
    markdown, _ = generate_report([rejected])
    assert "置信度 0%" in markdown
    assert "置信度 95%" not in markdown
