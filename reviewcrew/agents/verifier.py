from __future__ import annotations

import asyncio
import time
from pathlib import Path

from pydantic import BaseModel
from pydantic_ai import Agent, UnexpectedModelBehavior
from pydantic_ai.models import Model

from reviewcrew.events import EventLogger
from reviewcrew.llm.glm import (
    build_glm_model,
    build_model_settings,
    retry_unexpected_model_behavior,
    unlimited_usage,
)
from reviewcrew.models import Finding, PipelineEvent, Verdict
from reviewcrew.tools.toolbox import Toolbox

SEVERITY_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _confidence(finding: Finding) -> float:
    return (
        finding.confidence_adjusted
        if finding.confidence_adjusted is not None
        else finding.confidence
    )


class AgentVerdicts(BaseModel):
    verdicts: list[Verdict]


class VerifierAgent:
    def __init__(self, model: Model | None = None, event_logger: EventLogger | None = None) -> None:
        self.model = model
        self.event_logger = event_logger
        prompt = Path(__file__).parent / "prompts" / "verifier.md"
        self.system_prompt = prompt.read_text(encoding="utf-8")

    def _emit(self, event: PipelineEvent) -> None:
        if self.event_logger is not None:
            self.event_logger.emit(event)

    def _deterministic_verdicts(self, findings: list[Finding]) -> list[Verdict]:
        verdicts = []
        for finding in findings:
            normalized = finding.file.lower().replace("\\", "/")
            is_test = (
                normalized.startswith(("tests/", "test/", "examples/", "docs/"))
                or "/tests/" in normalized
                or Path(normalized).stem.startswith("test_")
            )
            verdicts.append(
                Verdict(
                    finding_id=finding.id,
                    verdict="reject" if is_test else "keep",
                    reason=(
                        "该位置仅属于测试或示例代码，不影响生产路径。"
                        if is_test
                        else "候选问题位于生产代码，保留其原始证据与置信度。"
                    ),
                    confidence_adjusted=(
                        min(finding.confidence, 0.3) if is_test else finding.confidence
                    ),
                )
            )
        return verdicts

    async def run(
        self,
        findings: list[Finding],
        toolbox: Toolbox,
        timeout_seconds: float = 120,
        task_id: str | None = None,
    ) -> list[Verdict]:
        del toolbox  # Reserved for model tools in the verifier's clean context.
        self._emit(
            PipelineEvent(
                timestamp=time.time(),
                type="agent",
                agent="verifier",
                agent_status="running",
                task_id=task_id,
            )
        )
        if not findings:
            return []
        try:
            async with asyncio.timeout(timeout_seconds):
                agent = Agent(
                    self.model or build_glm_model(),
                    output_type=AgentVerdicts,
                    system_prompt=self.system_prompt,
                    model_settings=build_model_settings(0.2),
                    retries=3,
                )
                prompt = "请独立验证以下候选问题，并用简体中文给出 verdict reason：\n" + "\n".join(
                    finding.model_dump_json() for finding in findings
                )
                result = await retry_unexpected_model_behavior(
                    lambda: agent.run(prompt, usage_limits=unlimited_usage())
                )
                verdicts = [
                    verdict.model_copy(
                        update={"confidence_adjusted": min(verdict.confidence_adjusted, 0.4)}
                    )
                    if verdict.verdict == "reject"
                    else verdict
                    for verdict in result.output.verdicts
                ]
        except (TimeoutError, ExceptionGroup, ValueError, UnexpectedModelBehavior):
            verdicts = self._deterministic_verdicts(findings)
        for verdict in verdicts:
            self._emit(
                PipelineEvent(
                    timestamp=time.time(), type="verdict", verdict=verdict, task_id=task_id
                )
            )
        self._emit(
            PipelineEvent(
                timestamp=time.time(),
                type="agent",
                agent="verifier",
                agent_status="done",
                task_id=task_id,
            )
        )
        return verdicts


def filter_and_rank(findings: list[Finding], verdicts: list[Verdict]) -> list[Finding]:
    by_id = {verdict.finding_id: verdict for verdict in verdicts}
    reviewed = []
    for finding in findings:
        verdict = by_id.get(finding.id)
        if verdict is None:
            reviewed.append(finding)
            continue
        reviewed.append(
            finding.model_copy(
                update={
                    "verdict": verdict.verdict,
                    "verdict_reason": verdict.reason,
                    "confidence_adjusted": verdict.confidence_adjusted,
                }
            )
        )
    return sorted(
        reviewed,
        key=lambda item: (
            item.verdict != "reject",
            SEVERITY_WEIGHT[item.severity] * _confidence(item)
        ),
        reverse=True,
    )
