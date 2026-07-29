"""Benchmark 判定逻辑测试 —— 三层命中判定：文件匹配、位置匹配、语义匹配。"""

from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _make_finding(
    finding_id: str = "f-001",
    file: str = "src/a.py",
    line_start: int = 10,
    line_end: int = 15,
) -> "Finding":
    """创建用于测试的 Finding 实例。"""
    from reviewcrew.schemas import Finding, CodeEvidence

    return Finding(
        id=finding_id,
        producer="defect",
        category="logic",
        severity="medium",
        confidence=0.8,
        file=file,
        line_start=line_start,
        line_end=line_end,
        title="测试缺陷",
        description="用于 Benchmark 判定的测试 Finding",
        trigger_condition="传入非法参数",
        impact="程序崩溃",
        reasoning_summary="逻辑错误导致异常",
        evidence=[
            CodeEvidence(
                file=file,
                line_start=line_start,
                line_end=line_end,
                content="def foo(): pass",
                language="python",
            )
        ],
    )


def _make_result(
    run_id: str = "r1",
    findings: list | None = None,
) -> "ReviewResult":
    """创建用于测试的 ReviewResult 实例。"""
    from reviewcrew.schemas import ReviewResult

    now = datetime.now(timezone.utc)
    return ReviewResult(
        run_id=run_id,
        status="completed",
        repository="test/repo",
        base_sha="abc",
        head_sha="def",
        findings=findings or [],
        rejected_count=0,
        coverage=[],
        warnings=[],
        started_at=now,
        completed_at=now,
        elapsed_seconds=0,
    )


def _make_entry(
    entry_id: str = "t-01",
    status: str = "ready",
    bug_locations: list | None = None,
) -> "DatasetEntry":
    """创建用于测试的 DatasetEntry 实例。"""
    from benchmark.models import DatasetEntry

    return DatasetEntry(
        id=entry_id,
        language="python",
        upstream_repo="https://github.com/example/repo",
        fork_repo="https://github.com/team/fork",
        source_fix_pr="https://github.com/example/repo/pull/1",
        test_pr="https://github.com/team/fork/pull/1",
        base_sha="abc",
        head_sha="def",
        introducing_commit="abc",
        fixing_commit="def",
        title="Test Case",
        bug_description="A test bug",
        severity="high",
        category="logic",
        status=status,
        bug_locations=bug_locations or [],
    )


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------

class TestJudgeFileMismatch:
    """文件不匹配判定测试。"""

    def test_judge_file_mismatch(self):
        """文件不匹配应判定为未命中。"""
        from benchmark.models import BugLocation
        from benchmark.judge import judge_case

        entry = _make_entry(
            bug_locations=[
                BugLocation(path="src/a.py", line_start=10, line_end=15)
            ],
        )
        # Finding 在完全不相关的文件中
        result = _make_result(
            findings=[_make_finding(file="src/other.py", line_start=1, line_end=5)],
        )
        judge = judge_case(entry, result)
        assert judge.caught is False

    def test_judge_file_match_wrong_path_case(self):
        """文件路径区分大小写，不匹配应判定未命中。"""
        from benchmark.models import BugLocation
        from benchmark.judge import judge_case

        entry = _make_entry(
            bug_locations=[
                BugLocation(path="src/A.py", line_start=10, line_end=15)
            ],
        )
        result = _make_result(
            findings=[_make_finding(file="src/a.py", line_start=10, line_end=15)],
        )
        judge = judge_case(entry, result)
        assert judge.caught is False


class TestJudgeLocationMatch:
    """位置匹配判定测试（含容差）。"""

    def test_judge_location_match_exact(self):
        """精确行号区间匹配应判定为命中。"""
        from benchmark.models import BugLocation
        from benchmark.judge import judge_case

        entry = _make_entry(
            bug_locations=[
                BugLocation(path="src/a.py", line_start=10, line_end=15)
            ],
        )
        result = _make_result(
            findings=[_make_finding(file="src/a.py", line_start=10, line_end=15)],
        )
        judge = judge_case(entry, result)
        assert judge.caught is True
        assert judge.location_match is True
        assert judge.used_line_tolerance is False

    def test_judge_location_match_overlap(self):
        """行号区间重叠应判定为命中。"""
        from benchmark.models import BugLocation
        from benchmark.judge import judge_case

        entry = _make_entry(
            bug_locations=[
                BugLocation(path="src/a.py", line_start=10, line_end=20)
            ],
        )
        # Finding 区间与目标区间部分重叠
        result = _make_result(
            findings=[_make_finding(file="src/a.py", line_start=15, line_end=25)],
        )
        judge = judge_case(entry, result)
        assert judge.caught is True
        assert judge.location_match is True

    def test_judge_location_match_with_tolerance(self):
        """行号在容差范围内（目标: 10-15, Finding: 20-25, 容差 +10 后覆盖）应命中。"""
        from benchmark.models import BugLocation
        from benchmark.judge import judge_case

        entry = _make_entry(
            bug_locations=[
                BugLocation(path="src/a.py", line_start=10, line_end=15)
            ],
        )
        # Finding 在目标之后，但在容差范围内
        # 目标: 10-15, tolerance=10 -> 检查范围: 0-25
        # Finding: 20-25, 与 0-25 重叠 → 命中
        result = _make_result(
            findings=[_make_finding(file="src/a.py", line_start=20, line_end=25)],
        )
        judge = judge_case(entry, result)
        assert judge.caught is True
        assert judge.used_line_tolerance is True

    def test_judge_location_beyond_tolerance(self):
        """行号超出容差范围（Finding 距离目标 > 10 行）应判定未命中。"""
        from benchmark.models import BugLocation
        from benchmark.judge import judge_case

        entry = _make_entry(
            bug_locations=[
                BugLocation(path="src/a.py", line_start=10, line_end=15)
            ],
        )
        # 目标: 10-15, tolerance=10 -> 0-25
        # Finding: 30-35, 不重叠 → 未命中
        result = _make_result(
            findings=[_make_finding(file="src/a.py", line_start=30, line_end=35)],
        )
        judge = judge_case(entry, result)
        assert judge.caught is False

    def test_judge_multiple_bug_locations(self):
        """多个 BugLocation 中任一个命中即判定为命中。"""
        from benchmark.models import BugLocation
        from benchmark.judge import judge_case

        entry = _make_entry(
            bug_locations=[
                BugLocation(path="src/a.py", line_start=100, line_end=110),
                BugLocation(path="src/b.py", line_start=10, line_end=20),
            ],
        )
        # 命中第二个 location
        result = _make_result(
            findings=[_make_finding(file="src/b.py", line_start=12, line_end=18)],
        )
        judge = judge_case(entry, result)
        assert judge.caught is True
        assert "src/b.py" in judge.reason


class TestJudgeSkipsNonReady:
    """非 ready 状态案例跳过判定测试。"""

    def test_judge_skips_needs_review(self):
        """needs_review 状态的案例应跳过判定。"""
        from benchmark.models import BugLocation
        from benchmark.judge import judge_case

        entry = _make_entry(
            status="needs_review",
            bug_locations=[
                BugLocation(path="src/a.py", line_start=10, line_end=15)
            ],
        )
        result = _make_result(
            findings=[_make_finding(file="src/a.py", line_start=10, line_end=15)],
        )
        judge = judge_case(entry, result)
        assert judge.caught is False
        assert "needs_review" in judge.reason

    def test_judge_skips_unavailable(self):
        """unavailable 状态的案例应跳过判定。"""
        from benchmark.models import BugLocation
        from benchmark.judge import judge_case

        entry = _make_entry(
            status="unavailable",
            bug_locations=[
                BugLocation(path="src/a.py", line_start=10, line_end=15)
            ],
        )
        result = _make_result(
            findings=[_make_finding(file="src/a.py", line_start=10, line_end=15)],
        )
        judge = judge_case(entry, result)
        assert judge.caught is False
        assert "unavailable" in judge.reason


class TestJudgeEmpty:
    """边界情况测试。"""

    def test_judge_empty_findings(self):
        """无 Finding 时应判定为未命中。"""
        from benchmark.models import BugLocation
        from benchmark.judge import judge_case

        entry = _make_entry(
            bug_locations=[
                BugLocation(path="src/a.py", line_start=10, line_end=15)
            ],
        )
        result = _make_result(findings=[])
        judge = judge_case(entry, result)
        assert judge.caught is False

    def test_judge_empty_bug_locations(self):
        """无 BugLocation 时应判定为未命中。"""
        from benchmark.judge import judge_case

        # 即使 Finding 存在，但没有目标位置就无法匹配
        entry = _make_entry(bug_locations=[])
        result = _make_result(
            findings=[_make_finding(file="src/a.py", line_start=10, line_end=15)],
        )
        judge = judge_case(entry, result)
        assert judge.caught is False
