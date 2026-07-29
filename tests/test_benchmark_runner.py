"""Benchmark Runner 测试 —— 数据集加载、Fake 模式运行和 CLI 入口。"""

import json
from pathlib import Path

import pytest


class TestLoadDataset:
    """数据集加载测试。"""

    def test_runner_loads_dataset_all(self):
        """load_dataset(ready_only=False) 应加载全部 5 个骨架案例。"""
        from benchmark.runner import load_dataset

        entries = load_dataset(ready_only=False)
        assert len(entries) == 5
        ids = {e.id for e in entries}
        assert ids == {"sentry-01", "calcom-01", "grafana-01", "keycloak-01", "discourse-01"}

    def test_runner_loads_dataset_ready_only(self):
        """load_dataset(ready_only=True) 应返回 0（所有案例均为 needs_review）。"""
        from benchmark.runner import load_dataset

        entries = load_dataset(ready_only=True)
        assert len(entries) == 0

    def test_runner_load_dataset_entries_have_required_fields(self):
        """加载的案例应包含所有必需字段。"""
        from benchmark.runner import load_dataset

        entries = load_dataset(ready_only=False)
        for entry in entries:
            assert entry.id
            assert entry.language
            assert entry.status == "needs_review"
            assert isinstance(entry.bug_locations, list)

    def test_runner_load_dataset_nonexistent_path(self):
        """不存在的文件路径应返回空列表并记录警告。"""
        from benchmark.runner import load_dataset

        entries = load_dataset(path="/nonexistent/dataset.yaml", ready_only=False)
        assert entries == []


class TestRunBenchmarkFake:
    """Fake 模式评测运行测试。"""

    def test_runner_fake_generates_output_files(self, tmp_path: Path):
        """Fake 模式应生成 cases.jsonl、summary.json 和 summary.md。"""
        from benchmark.runner import load_dataset, run_benchmark

        entries = load_dataset(ready_only=False)
        results_dir = tmp_path / "bench_results"
        result = run_benchmark(entries, results_dir=str(results_dir), runner="fake")

        # 验证输出文件存在
        assert (results_dir / "cases.jsonl").exists()
        assert (results_dir / "summary.json").exists()
        assert (results_dir / "summary.md").exists()

        # 验证 cases.jsonl 行数
        cases_lines = (results_dir / "cases.jsonl").read_text(encoding="utf-8").strip().split("\n")
        assert len(cases_lines) == 5

        # 验证每行是有效 JSON 且包含 entry 和 judge
        for line in cases_lines:
            data = json.loads(line)
            assert "entry" in data
            assert "judge" in data
            assert data["judge"]["caught"] is False  # needs_review 全部跳过

    def test_runner_fake_summary_content(self, tmp_path: Path):
        """Fake 模式生成的 summary.json 应包含命中率等关键字段。"""
        from benchmark.runner import load_dataset, run_benchmark

        entries = load_dataset(ready_only=False)
        results_dir = tmp_path / "bench_results"
        result = run_benchmark(entries, results_dir=str(results_dir), runner="fake")

        summary = result["summary"]
        assert summary["total"] == 5
        assert summary["completed"] == 5
        assert summary["caught"] == 0  # needs_review 全部跳过
        assert summary["catch_rate"] == "0%"
        assert summary["needs_review"] == 0
        assert "by_language" in summary
        assert "by_category" in summary

    def test_runner_fake_quick_mode(self, tmp_path: Path):
        """quick 模式 Fake 运行应正常跳过 needs_review 案例并生成结果。"""
        from benchmark.runner import load_dataset, run_benchmark

        entries = load_dataset(ready_only=True)
        # ready_only 过滤后无案例，run_benchmark 应能处理空列表
        results_dir = tmp_path / "bench_results_empty"
        result = run_benchmark(entries, results_dir=str(results_dir), runner="fake")
        assert result["summary"]["total"] == 0
        assert result["summary"]["catch_rate"] == "N/A"

    def test_runner_fake_result_structure(self, tmp_path: Path):
        """返回的 result dict 应包含 cases 和 summary。"""
        from benchmark.runner import load_dataset, run_benchmark

        entries = load_dataset(ready_only=False)
        results_dir = tmp_path / "bench_results"
        result = run_benchmark(entries, results_dir=str(results_dir), runner="fake")

        assert "cases" in result
        assert "summary" in result
        assert isinstance(result["cases"], list)
        assert len(result["cases"]) == 5


class TestRenderSummaryMd:
    """摘要 Markdown 渲染测试。"""

    def test_render_summary_md_contains_key_metrics(self):
        """摘要 Markdown 应包含总数、完成数和命中率。"""
        from benchmark.runner import render_summary_md

        summary = {
            "total": 5,
            "completed": 5,
            "caught": 2,
            "catch_rate": "40%",
            "needs_review": 1,
        }
        md = render_summary_md(summary)
        assert "总案例数: 5" in md
        assert "完成运行: 5" in md
        assert "成功命中: 2" in md
        assert "命中率: 40%" in md
        assert "需人工复核: 1" in md
