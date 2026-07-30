"""审查编排器 —— 阶段调度、预算管理和降级控制。

Orchestrator 负责确定性的任务调度，TeamLeadAgent 只产出计划和路由决策。
所有阶段超时通过 asyncio.timeout 强制执行，全局 watchdog 为 600 秒。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Config
from ..events import EventStore
from ..schemas import ReviewRequest, ReviewResult, PRData, ContextPack, Finding, PipelineEvent
from ..github.pr_loader import load_pr
from ..context.builder import build_context
from ..pipeline.dedupe import deduplicate_findings
from ..pipeline.report import render_markdown
from ..pipeline.static_reviewer import run_static_review
from ..agents.defect import DefectAgent
from ..agents.intent import IntentAgent
from ..agents.verifier import VerifierAgent

logger = logging.getLogger(__name__)


class Orchestrator:
    """审查编排器 —— 管理从 PR 输入到最终报告的全流程。"""

    def __init__(self, config: Config, events: EventStore) -> None:
        self.config = config
        self.events = events
        self.model: Any = None  # 由调用方注入

    async def review(self, request: ReviewRequest) -> ReviewResult:
        """执行一次完整的代码审查（便捷方法，自动创建 run_id）。"""
        run_id = self.events.create_run()
        return await self.review_with_run_id(run_id, request)

    async def review_with_run_id(
        self, run_id: str, request: ReviewRequest
    ) -> ReviewResult:
        """使用预创建的 run_id 执行审查（供 FastAPI 后台调用）。

        Args:
            run_id: 已创建的事件流 ID
            request: 审查请求

        Returns:
            完整审查结果
        """
        started_at = datetime.now(timezone.utc)
        warnings: list[str] = []
        all_findings: list[Finding] = []
        rejected = 0

        # 发射开始事件（如果还没发射）
        existing = self.events.read(run_id)
        if not any(e.type == "review.started" for e in existing):
            self.events.emit(run_id, "review.started", {"run_id": run_id})

        try:
            # 全局 watchdog
            async with asyncio.timeout(self.config.global_timeout_seconds):
                # 阶段 1: 加载 PR
                pr_data = await self._run_stage(
                    run_id, "loading_pr", "PR 加载",
                    self.config.pr_load_timeout_seconds,
                    load_pr(request, self.config),
                )

                # 阶段 2: 构建上下文
                repo_path = Path(request.repo_path) if request.repo_path else Path(".")
                if request.pr_url and not request.repo_path:
                    warnings.append(
                        "GitHub PR 模式下未提供本地仓库路径，将使用当前工作目录 "
                        "构建上下文。上下文可能不包含 PR 对应文件，请将仓库克隆到本地 "
                        "并指定 --repo 路径以获得完整上下文。"
                    )
                packs = await self._run_stage(
                    run_id, "building_context", "上下文构建",
                    self.config.context_timeout_seconds,
                    build_context(pr_data, repo_path, self.config),
                )

                # 阶段 3: 专家审查（并行运行 DefectAgent + IntentAgent）
                self.events.emit(run_id, "stage.started", {"stage": "reviewing"})
                self.events.emit(run_id, "agent.started", {
                    "agent": "defect", "agent_name": "缺陷检测 Agent",
                })
                self.events.emit(run_id, "agent.started", {
                    "agent": "intent", "agent_name": "意图分析 Agent",
                })

                use_llm = bool(self.config.llm_api_key.get_secret_value())

                if use_llm and packs:
                    logger.info("使用 LLM Agent 进行审查 (%s)", self.config.llm_model_name)
                    defect_agent = DefectAgent(None, agent_id="defect-1")
                    intent_agent = IntentAgent(None, agent_id="intent-1")

                    # 串行调用（避免 API 并发限制），最多审查 5 个文件
                    packs_to_review = packs[:5] if packs else []
                    defect_findings = await defect_agent.run(contexts=packs_to_review, pr_data=pr_data)
                    intent_findings = await intent_agent.run(contexts=packs_to_review, pr_data=pr_data)
                    all_findings.extend(defect_findings)
                    all_findings.extend(intent_findings)

                    self.events.emit(run_id, "agent.completed", {
                        "agent": "defect", "findings": len(defect_findings),
                    })
                    self.events.emit(run_id, "agent.completed", {
                        "agent": "intent", "findings": len(intent_findings),
                    })
                else:
                    # 降级：使用静态规则引擎
                    if not use_llm:
                        logger.warning("LLM 不可用，降级为静态规则审查")
                        warnings.append("LLM 未配置或不可用，使用静态规则引擎进行审查")
                    findings, rule_hits = run_static_review(pr_data)
                    all_findings.extend(findings)

                    self.events.emit(run_id, "agent.completed", {
                        "agent": "defect", "findings": len(findings),
                    })
                    self.events.emit(run_id, "agent.completed", {
                        "agent": "intent", "findings": 0,
                    })

                self.events.emit(run_id, "stage.completed", {"stage": "reviewing"})

                # 阶段 4: 去重
                if all_findings:
                    all_findings = deduplicate_findings(all_findings)

                # 阶段 5: Verifier（LLM 验证或降级为置信度过滤）
                if all_findings:
                    self.events.emit(run_id, "stage.started", {"stage": "verifying"})
                    self.events.emit(run_id, "verifier.started", {})
                    kept = []
                    rejected = 0

                    if use_llm:
                        logger.info("使用 LLM Verifier 验证 %d 个候选 Finding", len(all_findings))
                        verifier = VerifierAgent(None, agent_id="verifier-1")
                        context_prompt = (
                            f"PR: {pr_data.title}\n{pr_data.description[:1000]}\n"
                            f"Repository: {pr_data.repository}"
                        )
                        for f in all_findings:
                            try:
                                verdict = await verifier.verify_finding(f, context_prompt)
                                if verdict.accepted:
                                    # 应用 Verifier 调整后的严重度和置信度
                                    f.severity = verdict.severity if verdict.severity else f.severity
                                    f.confidence = verdict.confidence
                                    kept.append(f)
                                    self.events.emit(run_id, "verifier.accepted", {
                                        "finding_id": f.id,
                                        "reason": verdict.reason,
                                    })
                                else:
                                    rejected += 1
                                    self.events.emit(run_id, "verifier.rejected", {
                                        "finding_id": f.id,
                                        "reason": verdict.reason,
                                    })
                            except Exception as e:
                                logger.warning("Verifier 验证 %s 失败: %s，降级为置信度过滤", f.id, e)
                                if f.confidence >= 0.6:
                                    kept.append(f)
                                else:
                                    rejected += 1
                    else:
                        # 降级：纯置信度过滤
                        for f in all_findings:
                            if f.confidence >= 0.6:
                                kept.append(f)
                                self.events.emit(run_id, "verifier.accepted", {
                                    "finding_id": f.id,
                                    "reason": f"置信度 {f.confidence:.0%}，证据充分",
                                })
                            else:
                                rejected += 1
                                self.events.emit(run_id, "verifier.rejected", {
                                    "finding_id": f.id,
                                    "reason": f"置信度不足 ({f.confidence:.0%})",
                                })

                    all_findings = kept
                    self.events.emit(run_id, "verifier.completed", {
                        "accepted": len(kept), "rejected": rejected,
                    })
                    self.events.emit(run_id, "stage.completed", {"stage": "verifying"})

                # 阶段 6: 生成报告
                self.events.emit(run_id, "stage.started", {"stage": "generating_report"})
                elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
                result = ReviewResult(
                    run_id=run_id,
                    status="completed",
                    repository=pr_data.repository,
                    base_sha=pr_data.base_sha,
                    head_sha=pr_data.head_sha,
                    findings=all_findings[:8],  # 最多 8 条
                    rejected_count=rejected,
                    coverage=[],
                    warnings=warnings,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    elapsed_seconds=elapsed,
                )
                self.events.emit(run_id, "stage.completed", {"stage": "generating_report"})

        except asyncio.TimeoutError:
            warnings.append(f"审查超时（{self.config.global_timeout_seconds} 秒），已保存部分结果")
            elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
            result = ReviewResult(
                run_id=run_id,
                status="partial",
                repository=request.pr_url or request.repo_path or "unknown",
                base_sha="",
                head_sha="",
                findings=all_findings[:8],
                rejected_count=0,
                coverage=[],
                warnings=warnings,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                elapsed_seconds=elapsed,
            )

        except Exception as e:
            logger.error("审查失败: %s", e)
            warnings.append(f"审查异常: {e}")
            elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
            result = ReviewResult(
                run_id=run_id,
                status="failed",
                repository=request.pr_url or request.repo_path or "unknown",
                base_sha="",
                head_sha="",
                findings=[],
                rejected_count=0,
                coverage=[],
                warnings=warnings,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                elapsed_seconds=elapsed,
            )

        # 发射完成事件
        self.events.emit(run_id, "review.completed", {
            "status": result.status,
            "finding_count": len(result.findings),
            "elapsed_seconds": result.elapsed_seconds,
        })

        # 保存结果和报告
        self._save_result(run_id, result)
        self._save_report(run_id, result)

        return result

    async def _run_stage(
        self,
        run_id: str,
        stage_name: str,
        stage_label: str,
        timeout_seconds: float,
        coro: Any,
    ) -> Any:
        """在独立超时内运行一个阶段。

        Args:
            run_id: 运行 ID
            stage_name: 阶段标识
            stage_label: 中文阶段名
            timeout_seconds: 超时秒数
            coro: 要执行的协程

        Returns:
            阶段结果，超时或失败时抛出
        """
        self.events.emit(run_id, "stage.started", {
            "stage": stage_name,
            "label": stage_label,
        })
        try:
            async with asyncio.timeout(timeout_seconds):
                result = await coro
            self.events.emit(run_id, "stage.completed", {"stage": stage_name})
            return result
        except asyncio.TimeoutError:
            logger.warning("%s 阶段超时 (%ss)", stage_label, timeout_seconds)
            self.events.emit(run_id, "stage.failed", {
                "stage": stage_name,
                "reason": f"{stage_label}超时",
            })
            raise
        except Exception:
            logger.exception("%s 阶段失败", stage_label)
            self.events.emit(run_id, "stage.failed", {
                "stage": stage_name,
                "reason": f"{stage_label}失败",
            })
            raise

    def _save_result(self, run_id: str, result: ReviewResult) -> None:
        """保存 JSON 结果到 runs/{run_id}/result.json。"""
        run_dir = Path(self.config.runs_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "result.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )

    def _save_report(self, run_id: str, result: ReviewResult) -> None:
        """保存 Markdown 报告到 runs/{run_id}/report.md。"""
        run_dir = Path(self.config.runs_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "report.md").write_text(
            render_markdown(result), encoding="utf-8"
        )
