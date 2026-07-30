from __future__ import annotations

from reviewcrew.models import Finding
from reviewcrew.pipeline.dedupe import dedupe


def finding(file: str, start: int, confidence: float, category: str = "security") -> Finding:
    return Finding(
        category=category,
        severity="high",
        confidence=confidence,
        file=file,
        line_start=start,
        line_end=start + 4,
        title="SQL injection via string concatenation",
        reasoning="Untrusted input reaches a SQL query",
        trigger_path="request to database",
        suggestion="Use a parameterized query",
    )


def test_dedupe_line_overlap_keeps_confident() -> None:
    result = dedupe([finding("a.py", 10, 0.7), finding("a.py", 12, 0.9)])
    assert len(result) == 1
    assert result[0].confidence == 0.9
    assert result[0].id


def test_dedupe_injected_semantic_similarity() -> None:
    result = dedupe(
        [finding("a.py", 10, 0.7), finding("b.py", 30, 0.8)],
        similarity=lambda left, right: 0.9,
    )
    assert len(result) == 1


def test_different_categories_do_not_merge() -> None:
    result = dedupe(
        [finding("a.py", 10, 0.7), finding("b.py", 30, 0.8, "memory")],
        similarity=lambda left, right: 1.0,
    )
    assert len(result) == 2


def test_model_placeholder_ids_are_replaced_with_content_ids() -> None:
    left = finding("a.py", 10, 0.8).model_copy(update={"id": "F1"})
    right = finding("b.py", 20, 0.8).model_copy(
        update={"id": "F1", "title": "Authentication bypass in a separate handler"}
    )
    result = dedupe([left, right])
    assert len({item.id for item in result}) == 2
    assert all(item.id != "F1" for item in result)
