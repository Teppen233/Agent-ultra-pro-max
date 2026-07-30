"""Benchmark JSONL、JSON 与中文 Markdown 报告。"""

from __future__ import annotations

import json
from pathlib import Path

from collections.abc import Sequence
from typing import Literal

from benchmark.models import (
    BenchmarkSummary,
    CaseReport,
    FIVE_REPOSITORIES,
    RepositoryBenchmarkSummary,
    RepositoryBenchmarkTarget,
    RepositoryBenchmarkStatus,
)


def summarize_reports(
    reports: Sequence[CaseReport],
    *,
    all_repositories: Sequence[RepositoryBenchmarkTarget] = FIVE_REPOSITORIES,
    mode: Literal["quick", "case", "full"] = "full",
    runner: Literal["fake", "real"] = "real",
    offline: bool = False,
) -> BenchmarkSummary:
    """按固定仓库聚合案例报告，真实未完成案例不产生伪造的零命中率。"""

    grouped: dict[str, list[CaseReport]] = {}
    for report in reports:
        grouped.setdefault(report.project, []).append(report)

    targets = list(all_repositories)
    known_repositories = {target.repository for target in targets}
    for repository, repository_reports in grouped.items():
        if repository not in known_repositories:
            targets.append(
                RepositoryBenchmarkTarget(
                    repository=repository,
                    language=repository_reports[0].language,
                )
            )

    repositories = [
        _summarize_repository(
            target,
            grouped.get(target.repository, []),
            offline=offline,
        )
        for target in targets
    ]
    completed = [report for report in reports if report.status == "completed"]
    caught_cases = sum(report.judge.caught for report in completed)
    actually_run = len(completed)
    return BenchmarkSummary(
        mode=mode,
        runner=runner,
        offline=offline,
        selected_cases=len(reports),
        completed_cases=actually_run,
        actually_run_ready_cases=actually_run,
        caught_cases=caught_cases,
        real_catch_rate=(caught_cases / actually_run if not offline and actually_run else None),
        observed_offline_catch_rate=(caught_cases / actually_run if offline and actually_run else None),
        offline_results_excluded_from_real_rate=offline,
        false_positive_count=sum(report.judge.false_positive_count for report in reports),
        verifier_accepted_count=sum(report.judge.verifier_accepted_count for report in reports),
        verifier_rejected_count=sum(report.judge.verifier_rejected_count for report in reports),
        needs_human_review_cases=sum(report.judge.needs_human_review for report in reports),
        timed_out_cases=sum(report.timed_out for report in reports),
        elapsed_seconds=sum(report.elapsed_seconds for report in reports),
        repositories=repositories,
    )


def _summarize_repository(
    target: RepositoryBenchmarkTarget,
    reports: Sequence[CaseReport],
    *,
    offline: bool,
) -> RepositoryBenchmarkSummary:
    """聚合单仓案例，并将不完整执行与真实命中率分母隔离。"""

    completed = [report for report in reports if report.status == "completed"]
    status: RepositoryBenchmarkStatus
    if not reports:
        status = "pending"
    elif any(report.status == "partial" for report in reports):
        status = "partial"
    elif all(report.status == "failed" for report in reports):
        status = "failed"
    elif all(report.status == "completed" for report in reports):
        status = "completed"
    else:
        status = "partial"
    target_caught = sum(report.judge.caught for report in completed)
    completed_count = len(completed)
    observed_rate = target_caught / completed_count if offline and completed_count else None
    return RepositoryBenchmarkSummary(
        repository=target.repository,
        language=target.language,
        total_cases=len(reports),
        verified_cases=sum(report.status in {"completed", "partial"} for report in reports),
        executed_cases=len(reports),
        target_caught=target_caught,
        other_findings=sum(report.judge.false_positive_count for report in reports),
        rejected_count=sum(report.judge.verifier_rejected_count for report in reports),
        elapsed_seconds=sum(report.elapsed_seconds for report in reports),
        status=status,
        latest_run_id=next((report.run_id for report in reversed(reports) if report.run_id), None),
        catch_rate=(target_caught / completed_count if not offline and completed_count else None),
        observed_offline_catch_rate=observed_rate,
        cases=list(reports),
    )


def render_summary_markdown(summary: BenchmarkSummary, cases: list[CaseReport]) -> str:
    """渲染包含离线免责声明和误报统计的中文摘要。"""

    real_rate = "不适用" if summary.real_catch_rate is None else f"{summary.real_catch_rate:.2%}"
    observed_rate = (
        "不适用"
        if summary.observed_offline_catch_rate is None
        else f"{summary.observed_offline_catch_rate:.2%}"
    )
    lines = [
        "# ReviewCrew Greptile Benchmark 报告",
        "",
        f"- runner={summary.runner}",
        f"- offline={str(summary.offline).lower()}",
        f"- mode={summary.mode}",
        f"- 选择案例：{summary.selected_cases}",
        f"- 实际完成 ready 案例：{summary.actually_run_ready_cases}",
        f"- 命中案例：{summary.caught_cases}",
        f"- 真实命中率：{real_rate}",
        f"- 离线观察命中率：{observed_rate}",
        f"- 误报 Finding：{summary.false_positive_count}",
        f"- Verifier 接受/拒绝：{summary.verifier_accepted_count}/{summary.verifier_rejected_count}",
        f"- 超时案例：{summary.timed_out_cases}",
        f"- 需要人工复核：{summary.needs_human_review_cases}",
        f"- 总耗时：{summary.elapsed_seconds:.2f} 秒",
        "",
    ]
    if summary.offline_results_excluded_from_real_rate:
        lines.extend(
            [
                "> 当前为确定性离线 Fake 运行，只验证评测链路；结果不计入真实命中率。",
                "",
            ]
        )
    lines.extend(
        [
            "## 案例",
            "",
            "| 案例 | 项目 | 状态 | 命中 | 误报 | 判定 |",
            "|---|---|---|---:|---:|---|",
        ]
    )
    for case in cases:
        lines.append(
            f"| {case.case_id} | {case.project} | {case.status} | "
            f"{'是' if case.judge.caught else '否'} | {case.judge.false_positive_count} | "
            f"{case.judge.reason} |"
        )
    if summary.repositories:
        lines.extend(
            [
                "",
                "## 仓库汇总",
                "",
                "| 仓库 | 状态 | 已运行 | 目标命中 | 其他 Finding | 拒绝 | 真实命中率 |",
                "|---|---|---:|---:|---:|---:|---|",
            ]
        )
        for repository in summary.repositories:
            catch_rate = (
                "不适用"
                if repository.catch_rate is None
                else f"{repository.catch_rate:.2%}"
            )
            lines.append(
                f"| {repository.repository} | {repository.status} | "
                f"{repository.executed_cases} | {repository.target_caught} | "
                f"{repository.other_findings} | {repository.rejected_count} | {catch_rate} |"
            )
    return "\n".join(lines) + "\n"


def persist_benchmark_report(
    output_dir: Path,
    cases: list[CaseReport],
    summary: BenchmarkSummary,
) -> tuple[Path, Path, Path]:
    """以 UTF-8 写出逐案例 JSONL、汇总 JSON 和中文 Markdown。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    cases_path = output_dir / "cases.jsonl"
    summary_path = output_dir / "summary.json"
    markdown_path = output_dir / "summary.md"
    case_lines = [
        json.dumps(case.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        for case in cases
    ]
    cases_path.write_text("\n".join(case_lines) + ("\n" if case_lines else ""), encoding="utf-8")
    summary_path.write_text(
        json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_summary_markdown(summary, cases), encoding="utf-8")
    return cases_path, summary_path, markdown_path
