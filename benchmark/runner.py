"""Benchmark Runner —— quick/case 模式评测入口。

命令:
    python -m benchmark.runner --mode quick
    python -m benchmark.runner --case sentry-01
    python -m benchmark.runner --mode quick --runner fake
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from reviewcrew.schemas import ReviewResult

from .models import DatasetEntry, JudgeResult
from .judge import judge_case
from .report import generate_summary

logger = logging.getLogger(__name__)


def load_dataset(path: str | Path = "", ready_only: bool = True) -> list[DatasetEntry]:
    """从 dataset.yaml 加载案例。

    Args:
        path: 数据集文件路径，默认为 benchmark/dataset.yaml
        ready_only: 是否只加载 ready 状态的案例

    Returns:
        案例列表
    """
    if not path:
        path = Path(__file__).parent / "dataset.yaml"
    else:
        path = Path(path)

    if not path.exists():
        logger.warning("数据集文件不存在: %s", path)
        return []

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []

    entries = [DatasetEntry(**item) for item in data]
    if ready_only:
        entries = [e for e in entries if e.status == "ready"]
    return entries


def run_benchmark(
    dataset: list[DatasetEntry],
    results_dir: str | Path = "",
    runner: str = "fake",
) -> dict:
    """运行 Benchmark 评测。

    Args:
        dataset: 案例列表
        results_dir: 结果保存目录
        runner: 运行模式 (fake 或 live)

    Returns:
        包含 cases 和 summary 的结果字典
    """
    if not results_dir:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        results_dir = Path(__file__).parent / "results" / ts
    else:
        results_dir = Path(results_dir)

    results_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = results_dir / "runs"
    runs_dir.mkdir(exist_ok=True)

    cases = []
    for entry in dataset:
        logger.info("评测案例: %s (%s)", entry.id, entry.title)

        if runner == "live":
            # Live 模式：实际调用 ReviewCrew Orchestrator
            from reviewcrew.config import Config
            from reviewcrew.events import EventStore
            from reviewcrew.pipeline.orchestrator import Orchestrator
            from reviewcrew.schemas import ReviewRequest

            config = Config.from_env()
            store = EventStore(config.runs_dir)
            orch = Orchestrator(config, store)
            # 使用 Fake Model（Benchmark 离线测试场景）
            from reviewcrew.llm.glm import build_fake_model
            orch.model = build_fake_model()

            request = ReviewRequest(
                repo_path="",
                base_ref=entry.base_sha,
                head_ref=entry.head_sha,
            )
            logger.info("  [live] 启动 Orchestrator 审查: %s", entry.fork_repo)
            result = asyncio.run(orch.review(request))
        else:
            # Fake 模式：生成模拟结果（不调用任何外部服务）
            logger.info("  [fake] 生成模拟 ReviewResult（无实际审查）")
            result = ReviewResult(
                run_id=f"bench-{entry.id}",
                status="completed",
                repository=entry.fork_repo,
                base_sha=entry.base_sha,
                head_sha=entry.head_sha,
                findings=[],
                rejected_count=0,
                coverage=[],
                warnings=[],
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                elapsed_seconds=0,
            )

        judge = judge_case(entry, result)
        cases.append({
            "entry": entry.model_dump(),
            "judge": judge.model_dump(),
        })

    summary = generate_summary(dataset, [JudgeResult(**c["judge"]) for c in cases])

    # 保存结果
    cases_file = results_dir / "cases.jsonl"
    with open(cases_file, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    summary_file = results_dir / "summary.json"
    summary_file.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary_md = results_dir / "summary.md"
    summary_md.write_text(render_summary_md(summary), encoding="utf-8")

    logger.info("结果保存至: %s", results_dir)
    return {"cases": cases, "summary": summary}


def render_summary_md(summary: dict) -> str:
    """渲染评测摘要 Markdown。"""
    lines = [
        "# Benchmark 评测摘要",
        "",
        f"- 总案例数: {summary.get('total', 0)}",
        f"- 完成运行: {summary.get('completed', 0)}",
        f"- 成功命中: {summary.get('caught', 0)}",
        f"- 命中率: {summary.get('catch_rate', 'N/A')}",
        f"- 需人工复核: {summary.get('needs_review', 0)}",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(description="ReviewCrew Benchmark Runner")
    parser.add_argument("--mode", choices=["quick", "case"], default="quick")
    parser.add_argument("--case", type=str, help="单个案例 ID")
    parser.add_argument("--runner", choices=["fake", "live"], default="fake")
    args = parser.parse_args()

    dataset = load_dataset()

    if args.mode == "case" and args.case:
        dataset = [e for e in dataset if e.id == args.case]

    if not dataset:
        print("没有可运行的案例。请检查 benchmark/dataset.yaml")
        sys.exit(1)

    # quick 模式：每仓库取一个
    if args.mode == "quick":
        seen_repos = set()
        quick_set = []
        for e in dataset:
            if e.fork_repo not in seen_repos:
                quick_set.append(e)
                seen_repos.add(e.fork_repo)
        dataset = quick_set

    print(f"运行 {len(dataset)} 个案例 (runner={args.runner})")
    result = run_benchmark(dataset, runner=args.runner)
    print(f"完成！命中率: {result['summary'].get('catch_rate', 'N/A')}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
