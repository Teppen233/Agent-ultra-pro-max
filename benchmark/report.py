"""Benchmark JSONL、JSON 与中文 Markdown 报告。"""

from __future__ import annotations

import json
from pathlib import Path

from benchmark.models import BenchmarkSummary, CaseReport


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
