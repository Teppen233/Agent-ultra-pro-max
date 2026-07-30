from __future__ import annotations

import hashlib
import re
from collections.abc import Callable

from reviewcrew.models import Finding

Similarity = Callable[[Finding, Finding], float]


def stable_finding_id(finding: Finding) -> str:
    """Ignore model placeholders such as F1 and derive a run-stable ID."""
    identity = (
        f"{finding.file}:{finding.line_start}:{finding.line_end}:"
        f"{finding.category}:{finding.title}"
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", value.lower()))


def lexical_similarity(left: Finding, right: Finding) -> float:
    left_words = _words(f"{left.title} {left.reasoning} {left.trigger_path}")
    right_words = _words(f"{right.title} {right.reasoning} {right.trigger_path}")
    union = left_words | right_words
    return len(left_words & right_words) / len(union) if union else 0.0


def _line_duplicate(left: Finding, right: Finding) -> bool:
    return (
        left.file == right.file
        and left.line_start <= right.line_end + 3
        and left.line_end >= right.line_start - 3
    )


def dedupe(
    findings: list[Finding],
    similarity: Similarity = lexical_similarity,
    semantic_threshold: float = 0.85,
) -> list[Finding]:
    kept: list[Finding] = []
    for original in findings:
        finding = original.model_copy(update={"id": stable_finding_id(original)})
        duplicate_index = next(
            (
                position
                for position, existing in enumerate(kept)
                if _line_duplicate(existing, finding)
                or (
                    existing.category == finding.category
                    and similarity(existing, finding) >= semantic_threshold
                )
            ),
            None,
        )
        if duplicate_index is None:
            kept.append(finding)
        elif finding.confidence > kept[duplicate_index].confidence:
            kept[duplicate_index] = finding
    return kept
