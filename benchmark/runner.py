"""Greptile Benchmark quick/case/full 命令与 Fake/Real 后端接口。"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
import sys
from time import perf_counter
from typing import Literal, Protocol

import yaml

from reviewcrew.config import Config
from reviewcrew.pipeline.orchestrator import Orchestrator
from reviewcrew.schemas import CodeEvidence, Finding, ReviewRequest, ReviewResult

from benchmark.judge import judge_case
from benchmark.models import (
    FIVE_REPOSITORIES,
    BenchmarkSummary,
    CaseReport,
    DatasetEntry,
    JudgeResult,
    load_dataset,
)
from benchmark.report import persist_benchmark_report, summarize_reports


Mode = Literal["quick", "case", "full"]
ROOT = Path(__file__).parent


class ReviewRunner(Protocol):
    """Benchmark 后端最小接口。"""

    name: Literal["fake", "real"]
    offline: bool

    def run(self, entry: DatasetEntry) -> ReviewResult:
        """执行单个 ready 案例并返回 Verifier 最终结果。"""


class RealReviewRunner:
    """把已核验测试 PR 交给真实 ReviewCrew Orchestrator。"""

    name: Literal["real"] = "real"
    offline = False

    def __init__(
        self,
        executor: Callable[[DatasetEntry], ReviewResult] | None = None,
        *,
        config: Config | None = None,
        orchestrator_factory: Callable[[Config], Orchestrator] = Orchestrator,
    ) -> None:
        self._executor = executor
        self._config = config or Config()
        self._orchestrator_factory = orchestrator_factory

    def run(self, entry: DatasetEntry) -> ReviewResult:
        """拒绝离线 fixture，并把真实案例交给注入的 ReviewCrew 执行器。"""

        if entry.source_kind == "offline_fixture":
            raise ValueError("真实 Runner 不得运行离线 fixture")
        if self._executor is not None:
            return self._executor(entry)
        if not entry.test_pr:
            raise ValueError("真实 ready 案例缺少测试 PR")
        orchestrator = self._orchestrator_factory(self._config)
        return asyncio.run(orchestrator.review(ReviewRequest(pr_url=entry.test_pr)))


class FakeReviewRunner:
    """完全离线、确定性的 ReviewResult 生成器。"""

    name: Literal["fake"] = "fake"
    offline = True

    def run(self, entry: DatasetEntry) -> ReviewResult:
        """按案例 ID 返回固定 Finding，覆盖 Judge 的关键正反分支。"""

        if entry.source_kind != "offline_fixture":
            raise ValueError("Fake Runner 只运行 offline_fixture 案例")
        target = entry.bug_locations[0]
        file = target.file
        line_start = target.start_line
        line_end = target.end_line
        description = entry.mechanism_keywords[0]
        impact = entry.impact_keywords[0]
        rejected_count = 0
        if entry.project == "calcom":
            file = "fixture/wrong-file.ts"
        elif entry.project == "grafana":
            line_start = target.end_line + 13
            line_end = line_start + 1
        elif entry.project == "keycloak":
            description = "建议把局部变量改成更清晰的名称。"
            impact = "代码风格会更统一。"
        elif entry.project == "discourse":
            line_start = target.start_line - 10
            line_end = line_start
            rejected_count = 1
        finding = self._make_finding(
            entry,
            file=file,
            line_start=line_start,
            line_end=line_end,
            description=description,
            impact=impact,
        )
        timestamp = datetime(2026, 7, 29, 13, 0, tzinfo=UTC)
        return ReviewResult(
            run_id=f"fake-{entry.id}",
            status="completed",
            repository=entry.fork_repo or entry.upstream_repo,
            base_sha=entry.base_sha or "",
            head_sha=entry.head_sha or "",
            findings=[finding],
            rejected_count=rejected_count,
            coverage=[file],
            warnings=[],
            started_at=timestamp,
            completed_at=timestamp,
            elapsed_seconds=0.01,
        )

    @staticmethod
    def _make_finding(
        entry: DatasetEntry,
        *,
        file: str,
        line_start: int,
        line_end: int,
        description: str,
        impact: str,
    ) -> Finding:
        """构造一个代表 Verifier 最终接受项的确定性 Finding。"""

        timestamp = datetime(2026, 7, 29, 13, 0, tzinfo=UTC)
        evidence = CodeEvidence(
            source="fixture-diff",
            file=file,
            start_line=line_start,
            end_line=line_end,
            description=description,
            content="offline fixture content",
        )
        return Finding(
            id=f"fake-finding-{entry.id}",
            producer="defect",
            category="logic",
            severity=entry.severity or "medium",
            confidence=0.95,
            file=file,
            line_start=line_start,
            line_end=line_end,
            title=description,
            description=description,
            trigger_condition="执行离线 fixture 中的目标路径。",
            impact=impact,
            reasoning_summary="离线固定结果，不包含模型推理。",
            suggestion="按 fixture 的已知修复处理。",
            evidence=[evidence],
            created_at=timestamp,
        )


def make_backend(name: Literal["fake", "real"]) -> ReviewRunner:
    """按稳定名称创建 Benchmark 后端接口。"""

    return FakeReviewRunner() if name == "fake" else RealReviewRunner()


def select_cases(
    entries: Sequence[DatasetEntry],
    *,
    mode: Mode,
    case_id: str | None = None,
) -> list[DatasetEntry]:
    """从 ready 案例中实现 quick 每仓一例、case 精确选择和 full 全选。"""

    ready = [entry for entry in entries if entry.status == "ready"]
    if mode == "case":
        if not case_id:
            raise ValueError("case 模式必须提供 --case")
        selected = [entry for entry in ready if entry.id == case_id]
        if not selected:
            raise ValueError(f"case 不存在或尚未 ready：{case_id}")
        return selected
    if mode == "full":
        return ready
    selected_by_project: dict[str, DatasetEntry] = {}
    for entry in ready:
        selected_by_project.setdefault(entry.project, entry)
    return list(selected_by_project.values())


def execute_benchmark(
    entries: Sequence[DatasetEntry],
    *,
    mode: Mode,
    backend: ReviewRunner,
    output_dir: Path,
    case_id: str | None = None,
) -> BenchmarkSummary:
    """执行选定案例、运行 Judge，并持久化三种可审计输出。"""

    selected = select_cases(entries, mode=mode, case_id=case_id)
    reports: list[CaseReport] = []
    for entry in selected:
        started_at = perf_counter()
        try:
            result = backend.run(entry)
        except TimeoutError:
            elapsed_seconds = max(0.0, perf_counter() - started_at)
            reports.append(
                CaseReport(
                    case_id=entry.id,
                    project=entry.project,
                    language=entry.language,
                    status="failed",
                    elapsed_seconds=elapsed_seconds,
                    timed_out=True,
                    run_id=None,
                    judge=JudgeResult(
                        caught=False,
                        needs_human_review=True,
                        reason="Runner 执行超时，案例未进入真实命中率分母。",
                        false_positive_count=0,
                        verifier_accepted_count=0,
                        verifier_rejected_count=0,
                    ),
                )
            )
            continue
        except Exception:
            elapsed_seconds = max(0.0, perf_counter() - started_at)
            reports.append(
                CaseReport(
                    case_id=entry.id,
                    project=entry.project,
                    language=entry.language,
                    status="failed",
                    elapsed_seconds=elapsed_seconds,
                    timed_out=False,
                    run_id=None,
                    judge=JudgeResult(
                        caught=False,
                        needs_human_review=True,
                        reason="Runner 执行失败，案例未进入真实命中率分母。",
                        false_positive_count=0,
                        verifier_accepted_count=0,
                        verifier_rejected_count=0,
                    ),
                )
            )
            continue
        decision = judge_case(entry, result)
        timed_out = any(token in warning.casefold() for warning in result.warnings for token in ("timeout", "超时"))
        reports.append(
            CaseReport(
                case_id=entry.id,
                project=entry.project,
                language=entry.language,
                status=result.status,
                elapsed_seconds=result.elapsed_seconds,
                timed_out=timed_out,
                run_id=result.run_id,
                judge=decision,
            )
        )
    summary = summarize_reports(
        reports,
        mode=mode,
        runner=backend.name,
        offline=backend.offline,
        all_repositories=FIVE_REPOSITORIES,
    )
    persist_benchmark_report(output_dir, reports, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    """构造 quick/case/full 与 fake/real 命令参数。"""

    parser = argparse.ArgumentParser(description="运行 ReviewCrew Greptile Benchmark")
    parser.add_argument("--mode", choices=("quick", "case", "full"), default="quick")
    parser.add_argument("--runner", choices=("fake", "real"), default="fake")
    parser.add_argument("--case", dest="case_id")
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output-dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """运行 CLI；真实模式仅执行通过完整校验的 ready 测试 PR。"""

    args = build_parser().parse_args(argv)
    effective_mode: Mode = "case" if args.case_id else args.mode
    dataset_path = args.dataset or (
        ROOT / "fixtures" / "fake_dataset.yaml" if args.runner == "fake" else ROOT / "dataset.yaml"
    )
    output_dir = args.output_dir or ROOT / "results" / f"{args.runner}-{effective_mode}"
    try:
        entries = load_dataset(dataset_path, ready_only=True)
    except (OSError, ValueError, yaml.YAMLError):
        print("Benchmark 数据集无法读取或未通过校验。", file=sys.stderr)
        return 2
    if not entries:
        print("Benchmark 没有通过人工核验的 ready 案例，拒绝生成空成绩。", file=sys.stderr)
        return 2
    backend = make_backend(args.runner)
    try:
        summary = execute_benchmark(
            entries,
            mode=effective_mode,
            backend=backend,
            output_dir=output_dir,
            case_id=args.case_id,
        )
    except ValueError as error:
        print(f"Benchmark 参数错误：{error}", file=sys.stderr)
        return 2
    print(f"Benchmark 完成：{summary.selected_cases} 个案例；报告：{output_dir}")
    return 0 if summary.actually_run_ready_cases else 2


if __name__ == "__main__":
    raise SystemExit(main())
