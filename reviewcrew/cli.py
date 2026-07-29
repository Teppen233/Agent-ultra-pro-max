"""ReviewCrew 的中文命令行入口。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from reviewcrew.config import Config
from reviewcrew.pipeline.orchestrator import Orchestrator
from reviewcrew.schemas import ReviewRequest


OrchestratorFactory = Callable[[Config], object]


class _ParserExit(Exception):
    """把 argparse 的进程退出转换为可测试的返回码。"""

    def __init__(self, status: int, message: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class ChineseArgumentParser(argparse.ArgumentParser):
    """统一输出中文参数错误，并禁止库调用路径抛出 SystemExit。"""

    def error(self, message: str) -> None:
        raise _ParserExit(2, "参数错误：命令、选项或必填参数无效，请检查后重试。")

    def exit(self, status: int = 0, message: str | None = None) -> None:
        if status == 0:
            raise _ParserExit(0)
        raise _ParserExit(status, "参数错误：命令行解析失败。")


def build_parser() -> argparse.ArgumentParser:
    """构造 review 与 replay 两个基础子命令。"""

    parser = ChineseArgumentParser(prog="reviewcrew", description="ReviewCrew 智能代码审查")
    commands = parser.add_subparsers(dest="command", parser_class=ChineseArgumentParser)
    review = commands.add_parser("review", help="审查 GitHub PR 或本地 base/head")
    review.add_argument("--pr", help="GitHub PR URL")
    review.add_argument("--repo", help="本地 Git 仓库路径")
    review.add_argument("--base", help="本地基准引用")
    review.add_argument("--head", help="本地目标引用")
    replay = commands.add_parser("replay", help="回放已持久化的运行事件")
    replay.add_argument("--run-id", required=True, help="历史运行 ID")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    config: Config | None = None,
    orchestrator_factory: OrchestratorFactory = Orchestrator,
) -> int:
    """执行 CLI，并以返回码区分成功、参数错误和审查失败。"""

    effective_config = config or Config.from_env()
    parser = build_parser()
    try:
        arguments = parser.parse_args(list(argv) if argv is not None else None)
        if arguments.command == "review":
            request = _review_request(arguments)
            return asyncio.run(_run_review(request, effective_config, orchestrator_factory))
        if arguments.command == "replay":
            return _run_replay(arguments.run_id, effective_config)
        raise ValueError("请指定 review 或 replay 子命令")
    except _ParserExit as error:
        if error.message:
            print(f"错误：{error.message}", file=sys.stderr)
        return error.status
    except ValueError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("错误：用户已中止运行。", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"错误：命令执行失败（{type(error).__name__}）。", file=sys.stderr)
        return 1


def _review_request(arguments: argparse.Namespace) -> ReviewRequest:
    """将互斥 CLI 参数转换为统一 ReviewRequest。"""

    local_values = (arguments.repo, arguments.base, arguments.head)
    if arguments.pr and any(local_values):
        raise ValueError("--pr 不能与本地 --repo、--base、--head 同时使用")
    if arguments.pr:
        return ReviewRequest(pr_url=arguments.pr)
    if any(local_values) and not all(local_values):
        raise ValueError("本地模式必须同时提供 --repo、--base 和 --head")
    if all(local_values):
        return ReviewRequest(repo_path=arguments.repo, base_ref=arguments.base, head_ref=arguments.head)
    raise ValueError("review 必须提供 --pr，或完整的 --repo、--base 和 --head")


async def _run_review(
    request: ReviewRequest,
    config: Config,
    orchestrator_factory: OrchestratorFactory,
) -> int:
    """运行审查并输出不包含 Prompt 或模型响应的中文摘要。"""

    if request.pr_url is not None:
        print(f"开始审查 GitHub PR：{request.pr_url}")
    else:
        print(f"开始审查本地仓库：{request.repo_path}（{request.base_ref} → {request.head_ref}）")
    orchestrator = orchestrator_factory(config)
    result = await orchestrator.review(request)
    if result.status == "failed":
        print(f"审查失败，运行 ID：{result.run_id}", file=sys.stderr)
        for warning in result.warnings:
            print(f"警告：{warning}", file=sys.stderr)
        return 1
    label = "审查完成" if result.status == "completed" else "审查部分完成"
    print(f"{label}，运行 ID：{result.run_id}，确认问题：{len(result.findings)}")
    print(f"报告目录：{Path(config.runs_dir) / result.run_id}")
    for warning in result.warnings:
        print(f"警告：{warning}")
    return 0


def _run_replay(run_id: str, config: Config) -> int:
    """按持久化顺序输出历史事件的基础文本回放。"""

    run_dir = Path(config.runs_dir) / run_id
    if not run_dir.is_dir():
        raise ValueError(f"未找到运行：{run_id}")
    events = Orchestrator.read_events(config.runs_dir, run_id)
    if not events:
        raise ValueError(f"运行 {run_id} 没有可回放事件")
    print(f"回放运行：{run_id}（共 {len(events)} 个事件）")
    for event in events:
        print(f"[{event.sequence}] {event.type}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
