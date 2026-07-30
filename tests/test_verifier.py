from __future__ import annotations

from reviewcrew.agents.verifier import VerifierAgent, filter_and_rank
from reviewcrew.models import Finding, Verdict


def finding(identifier: str, severity: str = "high", confidence: float = 0.8) -> Finding:
    return Finding(
        id=identifier,
        category="security",
        severity=severity,
        confidence=confidence,
        file="app.py",
        line_start=10,
        line_end=12,
        title="Reachable injection",
        reasoning="Untrusted data reaches a command",
        trigger_path="request -> command",
        suggestion="Use a safe API",
    )


async def test_verifier_deterministically_rejects_test_code() -> None:
    item = finding("one").model_copy(update={"file": "tests/test_auth.py"})
    verifier = VerifierAgent()
    verdicts = verifier._deterministic_verdicts([item])
    assert verdicts[0].verdict == "reject"


def test_filter_rank_preserves_all_candidates_and_orders_risk() -> None:
    findings = [
        finding(str(index), "critical" if index == 9 else "high", 0.9) for index in range(10)
    ]
    verdicts = [
        Verdict(
            finding_id=str(index),
            verdict="keep",
            reason="reachable",
            confidence_adjusted=0.5 if index == 0 else 0.9,
        )
        for index in range(10)
    ]
    result = filter_and_rank(findings, verdicts)
    assert len(result) == 10
    assert result[0].severity == "critical"
    assert next(item for item in result if item.id == "0").confidence_adjusted == 0.5


def test_filter_rank_preserves_rejected_candidate_with_reason() -> None:
    candidate = finding("one")
    result = filter_and_rank(
        [candidate],
        [
            Verdict(
                finding_id="one",
                verdict="reject",
                reason="contradicted",
                confidence_adjusted=0.1,
            )
        ],
    )
    assert len(result) == 1
    assert result[0].verdict == "reject"
    assert result[0].verdict_reason == "contradicted"
