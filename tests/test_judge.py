from __future__ import annotations

from benchmark.judge import BugLocation, DatasetEntry, judge
from reviewcrew.models import Finding


def finding(file: str = "a.py", start: int = 45) -> Finding:
    return Finding(
        category="security",
        severity="high",
        confidence=0.8,
        file=file,
        line_start=start,
        line_end=start + 3,
        title="SQL injection",
        reasoning="SQL query uses untrusted input",
        trigger_path="request -> query",
        suggestion="Use parameters",
    )


def entry() -> DatasetEntry:
    return DatasetEntry(
        repo="owner/repo",
        fork_url="https://github.com/fork/repo",
        pr_url="https://github.com/owner/repo/pull/1",
        base_sha="a",
        head_sha="b",
        bug_desc="SQL injection",
        bug_files=[BugLocation(path="a.py", line_start=46, line_end=50)],
        category="security",
    )


def test_judge_line_overlap_hit() -> None:
    result = judge([finding()], entry())
    assert result.hit is True
    assert result.reason == "line_overlap"


def test_judge_semantic_fallback() -> None:
    result = judge([finding("b.py")], entry(), semantic_matcher=lambda finding, entry: True)
    assert result.hit is True
    assert result.reason == "semantic_match"


def test_judge_miss() -> None:
    assert judge([finding("b.py")], entry()).hit is False
