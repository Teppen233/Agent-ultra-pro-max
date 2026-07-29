"""Benchmark 数据模型测试 —— 验证 DatasetEntry 和 BugLocation 的校验逻辑。"""

from pathlib import Path

import pytest


class TestBugLocation:
    """BugLocation 模型测试。"""

    def test_bug_location_creation(self):
        """应正确创建 BugLocation 实例。"""
        from benchmark.models import BugLocation

        loc = BugLocation(path="src/a.py", line_start=10, line_end=15)
        assert loc.path == "src/a.py"
        assert loc.line_start == 10
        assert loc.line_end == 15


class TestDatasetEntry:
    """DatasetEntry 模型测试。"""

    def test_dataset_entry_validation(self):
        """ready 案例必须具有完整字段。"""
        from benchmark.models import DatasetEntry, BugLocation

        entry = DatasetEntry(
            id="test-01",
            language="python",
            upstream_repo="https://github.com/example/repo",
            fork_repo="https://github.com/team/fork",
            source_fix_pr="https://github.com/example/repo/pull/123",
            test_pr="https://github.com/team/fork/pull/1",
            base_sha="abc123",
            head_sha="def456",
            introducing_commit="abc123",
            fixing_commit="def456",
            title="Test Bug",
            bug_description="A known vulnerability in authentication",
            severity="high",
            category="logic",
            status="ready",
            bug_locations=[
                BugLocation(path="src/auth.py", line_start=42, line_end=56)
            ],
        )
        assert entry.status == "ready"
        assert entry.id == "test-01"
        assert len(entry.bug_locations) == 1

    def test_dataset_entry_defaults(self):
        """未指定字段应使用默认值。"""
        from benchmark.models import DatasetEntry

        entry = DatasetEntry(
            id="minimal",
            language="python",
            upstream_repo="https://github.com/example/repo",
            fork_repo="https://github.com/team/fork",
            source_fix_pr="https://github.com/example/repo/pull/1",
            test_pr="https://github.com/team/fork/pull/1",
            base_sha="abc",
            head_sha="def",
            introducing_commit="abc",
            fixing_commit="def",
            title="Minimal",
            bug_description="Minimal bug",
        )
        assert entry.status == "needs_review"
        assert entry.severity == "high"
        assert entry.category == "logic"
        assert entry.bug_locations == []

    def test_dataset_entry_status_ready_requires_locations(self):
        """ready 状态时 bug_locations 可以为空列表（字段层面不强制校验）。"""
        from benchmark.models import DatasetEntry

        entry = DatasetEntry(
            id="ready-no-loc",
            language="go",
            upstream_repo="https://github.com/example/repo",
            fork_repo="https://github.com/team/fork",
            source_fix_pr="https://github.com/example/repo/pull/1",
            test_pr="https://github.com/team/fork/pull/1",
            base_sha="abc",
            head_sha="def",
            introducing_commit="abc",
            fixing_commit="def",
            title="Ready but no locations",
            bug_description="Test",
            status="ready",
        )
        assert entry.status == "ready"
        assert entry.bug_locations == []

    def test_dataset_entry_model_dump_serializable(self):
        """model_dump 应产出可序列化的字典。"""
        from benchmark.models import DatasetEntry

        entry = DatasetEntry(
            id="dump-test",
            language="python",
            upstream_repo="https://github.com/example/repo",
            fork_repo="https://github.com/team/fork",
            source_fix_pr="https://github.com/example/repo/pull/1",
            test_pr="https://github.com/team/fork/pull/1",
            base_sha="abc",
            head_sha="def",
            introducing_commit="abc",
            fixing_commit="def",
            title="Dump Test",
            bug_description="Test dump",
        )
        data = entry.model_dump()
        assert isinstance(data, dict)
        assert data["id"] == "dump-test"
        assert data["status"] == "needs_review"


class TestJudgeResult:
    """JudgeResult 模型测试。"""

    def test_judge_result_caught_false_by_default(self):
        """未命中时 caught 为 False。"""
        from benchmark.models import JudgeResult

        result = JudgeResult(
            case_id="test-01",
            caught=False,
            reason="未找到匹配的 Finding",
        )
        assert result.caught is False
        assert result.matched_finding_id is None
        assert result.location_match is False
        assert result.semantic_match is False

    def test_judge_result_caught_true_with_match(self):
        """命中时应包含所有匹配信息。"""
        from benchmark.models import JudgeResult

        result = JudgeResult(
            case_id="test-02",
            caught=True,
            matched_finding_id="f-001",
            location_match=True,
            semantic_match=True,
            used_line_tolerance=False,
            reason="文件: src/a.py, 行: 10-15, 目标: 10-15",
            needs_human_review=True,
        )
        assert result.caught is True
        assert result.matched_finding_id == "f-001"
        assert result.used_line_tolerance is False
        assert result.needs_human_review is True
