"""CLI 入口 —— 命令行审查和 Replay 工具。

使用方法:
    python -m reviewcrew.cli review --pr https://github.com/owner/repo/pull/1
    python -m reviewcrew.cli review --repo /path/to/repo --base main --head feature/x
    python -m reviewcrew.cli replay --run-id abc123
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .config import Config
from .events import EventStore
from .pipeline.orchestrator import Orchestrator
from .schemas import ReviewRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("reviewcrew.cli")


def main() -> None:
    """CLI 主入口。"""
    parser = argparse.ArgumentParser(
        description="ReviewCrew - AI Code Review 系统",
        prog="reviewcrew",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # review 子命令
    review_parser = sub.add_parser("review", help="启动代码审查")
    review_parser.add_argument(
        "--pr", type=str, help="GitHub PR URL"
    )
    review_parser.add_argument(
        "--repo", type=str, help="本地仓库路径"
    )
    review_parser.add_argument(
        "--base", type=str, help="基准引用（与 --repo 配合使用）"
    )
    review_parser.add_argument(
        "--head", type=str, help="目标引用（与 --repo 配合使用）"
    )
    review_parser.add_argument(
        "--fake",
        action="store_true",
        help="强制使用 Fake/Test 模型（离线模式，不调用 LLM）",
    )

    # replay 子命令
    replay_parser = sub.add_parser("replay", help="回放历史运行")
    replay_parser.add_argument(
        "--run-id", type=str, required=True, help="要回放的运行 ID"
    )

    args = parser.parse_args()

    if args.command == "review":
        request = ReviewRequest(
            pr_url=args.pr,
            repo_path=args.repo,
            base_ref=args.base,
            head_ref=args.head,
        )
    elif args.command == "replay":
        request = ReviewRequest(replay_run_id=args.run_id)
    else:
        parser.print_help()
        sys.exit(1)

    asyncio.run(_run_review(request, fake=args.fake if hasattr(args, "fake") else False))


async def _run_review(request: ReviewRequest, fake: bool = False) -> None:
    """执行审查并输出结果。"""
    config = Config.from_env()
    store = EventStore(config.runs_dir)

    orch = Orchestrator(config, store)

    # 模型选择：--fake 优先，否则根据 API Key 是否存在选择
    if fake:
        from .llm.glm import build_fake_model
        orch.model = build_fake_model()
        logger.warning("使用 Fake/Test 模型（--fake 模式），不会调用真实 LLM")
    else:
        api_key = config.llm_api_key.get_secret_value()
        if api_key:
            from .llm.glm import build_model
            orch.model = build_model(config)
            logger.info("使用 LLM 模型: %s", config.llm_model_name)
        else:
            from .llm.glm import build_fake_model
            orch.model = build_fake_model()
            logger.warning(
                "LLM_API_KEY 未设置，自动回退到 Fake/Test 模型。"
                "如需使用真实 LLM，请设置 LLM_API_KEY 环境变量。"
            )

    logger.info("启动审查...")
    result = await orch.review(request)

    logger.info("审查完成: %s", result.status)
    logger.info("发现 %d 条问题", len(result.findings))
    logger.info("耗时 %.1f 秒", result.elapsed_seconds)
    logger.info("运行 ID: %s", result.run_id)
    logger.info("报告: runs/%s/report.md", result.run_id)


if __name__ == "__main__":
    main()
