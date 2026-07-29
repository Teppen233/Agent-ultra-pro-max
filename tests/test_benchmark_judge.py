"""Greptile Benchmark 三层 Judge 测试。"""

from datetime import UTC, datetime
from importlib import import_module

import pytest

from reviewcrew.schemas import CodeEvidence, Finding, ReviewResult


NOW = datetime(2026, 7, 29, 13, 0, tzinfo=UTC)


def benchmark_modules():
    """延迟导入待实现的模型和 Judge。"""

    return import_module("benchmark.models"), import_module("benchmark.judge")


def make_entry(*, tolerance: int = 0):
    """构造包含明确机制、影响和目标位置的离线 ready 案例。"""

    models, _ = benchmark_modules()
    return models.DatasetEntry.model_validate(
        {
            "id": "sentry-offline-01",
            "project": "sentry",
            "title": "分页器导入错误",
            "language": "Python",
            "severity": "high",
            "status": "ready",
            "source_kind": "offline_fixture",
            "source_url": "fixture://greptile/sentry-01",
            "upstream_repo": "fixture/getsentry-sentry",
            "fork_repo": "fixture/reviewcrew-sentry",
            "test_pr": "fixture://reviewcrew/sentry/pr/1",
            "source_fix_pr": "fixture://reviewcrew/sentry/source-fix/1",
            "base_sha": "fixture-sentry-base",
            "head_sha": "fixture-sentry-head",
            "introducing_commit": "fixture-sentry-introducing",
            "fixing_commit": "fixture-sentry-fixing",
            "bug_locations": [
                {"file": "src/pagination.py", "start_line": 40, "end_line": 42}
            ],
            "bug_description": "导入不存在的分页器会导致模块加载失败。",
            "mechanism_keywords": ["不存在的分页器"],
            "impact_keywords": ["模块加载失败"],
            "line_tolerance": tolerance,
        }
    )


def make_finding(
    *,
    finding_id: str = "finding-1",
    file: str = "src/pagination.py",
    line_start: int = 40,
    line_end: int = 42,
    description: str = "这里导入了不存在的分页器。",
    impact: str = "应用启动时模块加载失败。",
) -> Finding:
    """构造已由 Verifier 接受并进入 ReviewResult 的 Finding。"""

    evidence = CodeEvidence(
        source="diff",
        file=file,
        start_line=line_start,
        end_line=line_end,
        description=description,
        content="from pagination import MissingPaginator",
    )
    return Finding(
        id=finding_id,
        producer="defect",
        category="static",
        severity="high",
        confidence=0.95,
        file=file,
        line_start=line_start,
        line_end=line_end,
        title="导入目标不存在",
        description=description,
        trigger_condition="加载分页模块。",
        impact=impact,
        reasoning_summary="仅供模型内部使用。",
        suggestion="改为存在的分页器。",
        evidence=[evidence],
        created_at=NOW,
    )


def make_result(
    findings: list[Finding],
    *,
    rejected_count: int = 0,
    status: str = "completed",
) -> ReviewResult:
    """构造最终审查结果；其中 findings 只包含 Verifier 接受项。"""

    return ReviewResult(
        run_id="run-sentry-offline-01",
        status=status,
        repository="fixture/reviewcrew-sentry",
        base_sha="fixture-sentry-base",
        head_sha="fixture-sentry-head",
        findings=findings,
        rejected_count=rejected_count,
        coverage=["src/pagination.py"],
        warnings=[],
        started_at=NOW,
        completed_at=NOW,
        elapsed_seconds=0.1,
    )


def test_judge_catches_direct_file_line_and_semantic_match() -> None:
    """文件、重叠位置、错误机制和实际影响全部一致时才直接命中。"""

    _, judge = benchmark_modules()
    decision = judge.judge_case(make_entry(), make_result([make_finding()]))

    assert decision.caught is True
    assert decision.matched_finding_id == "finding-1"
    assert decision.location_match is True
    assert decision.semantic_match is True
    assert decision.used_line_tolerance == 0
    assert decision.false_positive_count == 0


@pytest.mark.parametrize(
    ("file", "line_start", "line_end", "description", "impact", "reason_fragment"),
    [
        ("src/other.py", 40, 42, "导入了不存在的分页器。", "模块加载失败。", "文件"),
        ("src/pagination.py", 55, 56, "导入了不存在的分页器。", "模块加载失败。", "位置"),
        ("src/pagination.py", 40, 42, "建议调整导入排序。", "代码风格更统一。", "语义"),
    ],
)
def test_judge_rejects_wrong_file_distant_line_or_different_semantics(
    file: str,
    line_start: int,
    line_end: int,
    description: str,
    impact: str,
    reason_fragment: str,
) -> None:
    """任一层不匹配都不能命中，并将该接受 Finding 计为非目标误报。"""

    _, judge = benchmark_modules()
    finding = make_finding(
        file=file,
        line_start=line_start,
        line_end=line_end,
        description=description,
        impact=impact,
    )
    decision = judge.judge_case(make_entry(tolerance=10), make_result([finding]))

    assert decision.caught is False
    assert decision.false_positive_count == 1
    assert reason_fragment in decision.reason


@pytest.mark.parametrize(("line_start", "line_end"), [(30, 30), (52, 52)])
def test_judge_accepts_explicit_ten_line_tolerance_on_either_side(
    line_start: int,
    line_end: int,
) -> None:
    """目标前后恰好十行仅在案例显式允许时命中，并记录实际容差。"""

    _, judge = benchmark_modules()
    finding = make_finding(line_start=line_start, line_end=line_end)
    decision = judge.judge_case(make_entry(tolerance=10), make_result([finding]))

    assert decision.caught is True
    assert decision.used_line_tolerance == 10


def test_judge_never_revives_verifier_rejected_finding() -> None:
    """Verifier 拒绝项不会进入最终 findings，因此 Judge 不能自行把它恢复为命中。"""

    _, judge = benchmark_modules()
    decision = judge.judge_case(make_entry(), make_result([], rejected_count=1))

    assert decision.caught is False
    assert decision.matched_finding_id is None
    assert decision.verifier_accepted_count == 0
    assert decision.verifier_rejected_count == 1
    assert decision.false_positive_count == 0
    assert "Verifier" in decision.reason


def test_semantic_rejection_preserves_that_location_layer_passed() -> None:
    """分层结果需显示文件和位置已命中，只是机制/影响语义不足。"""

    _, judge = benchmark_modules()
    finding = make_finding(description="建议整理导入顺序。", impact="代码更易读。")
    decision = judge.judge_case(make_entry(), make_result([finding]))

    assert decision.caught is False
    assert decision.location_match is True
    assert decision.semantic_match is False
    assert decision.used_line_tolerance == 0


def test_judge_counts_unmatched_accepted_findings_as_false_positives() -> None:
    """命中率不扣误报，但报告必须单独统计所有未匹配的接受 Finding。"""

    _, judge = benchmark_modules()
    matching = make_finding(finding_id="matching")
    unrelated = make_finding(
        finding_id="unrelated",
        file="src/other.py",
        description="另一个文件的缓存可能过期。",
        impact="用户读取到旧数据。",
    )
    decision = judge.judge_case(make_entry(), make_result([unrelated, matching]))

    assert decision.caught is True
    assert decision.matched_finding_id == "matching"
    assert decision.false_positive_count == 1


def test_judge_does_not_count_second_matching_finding_as_false_positive() -> None:
    """多个 Finding 都准确描述同一目标时只选一个代表 ID，但其余命中项不是误报。"""

    _, judge = benchmark_modules()
    first = make_finding(finding_id="matching-1")
    second = make_finding(finding_id="matching-2")
    decision = judge.judge_case(make_entry(), make_result([first, second]))

    assert decision.caught is True
    assert decision.matched_finding_id == "matching-1"
    assert decision.false_positive_count == 0
