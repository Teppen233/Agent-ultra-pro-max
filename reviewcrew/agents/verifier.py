"""流式消费候选并寻找反证的 Verifier Agent。"""

from __future__ import annotations

import asyncio
from collections import deque
import json
from pathlib import Path
from typing import Any, Sequence

from pydantic_ai.models import Model

from reviewcrew.agents.base import AgentRuntime, PromptSource
from reviewcrew.config import Config
from reviewcrew.schemas import Budget, EvidenceResponse, Finding, TeamMessage, Verdict, VerificationRequest
from reviewcrew.skills.registry import SkillRegistry
from reviewcrew.team.blackboard import EvidenceBlackboard
from reviewcrew.team.mailbox import Mailbox
from reviewcrew.team.publisher import MessagePublisher


class VerifierAgent:
    """在专家运行期间逐条验证候选，而不主动发现新问题。"""

    def __init__(
        self,
        model: Model | None = None,
        *,
        skills_root: Path | None = None,
        config: Config | None = None,
        runtime: AgentRuntime | None = None,
        tools: Sequence[Any] = (),
        publisher: MessagePublisher | None = None,
        evidence_deadline_seconds: float = 30.0,
        confidence_threshold: float = 0.6,
        max_findings: int = 8,
    ) -> None:
        self._model = model
        self._skills_root = skills_root or Path(__file__).parent.parent / "skills"
        self._config = config or Config()
        self._runtime = runtime or AgentRuntime(config=self._config)
        self._tools = tuple(tools)
        self._publisher = publisher
        self._evidence_deadline_seconds = evidence_deadline_seconds
        self._confidence_threshold = confidence_threshold
        self._max_findings = max_findings

    async def watch(
        self,
        mailbox: Mailbox,
        blackboard: EvidenceBlackboard,
        budget: Budget,
    ) -> list[Verdict]:
        """监听候选消息，立即验证并在专家终态或预算截止时收敛。"""

        mailbox.register("verifier")
        publisher = self._publisher or MessagePublisher(mailbox=mailbox, blackboard=blackboard)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + budget.seconds
        deferred: deque[TeamMessage] = deque()
        seen_candidates: set[str] = set()
        terminal_roles = self._terminal_roles(blackboard.messages)
        verdicts: list[Verdict] = []
        accepted_count = 0
        timed_out = False
        try:
            for message in tuple(blackboard.by_kind("candidate_finding")):
                deferred.append(message)
            while terminal_roles != {"defect", "intent"} or deferred:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    message = deferred.popleft() if deferred else await mailbox.receive_one("verifier", timeout=remaining)
                except TimeoutError:
                    timed_out = True
                    break
                if message.kind == "cancel":
                    await self._publish_terminal(publisher, failed=True, warning="Verifier 收到取消消息。")
                    return verdicts
                role = self._terminal_role(message)
                if role is not None:
                    terminal_roles.add(role)
                    continue
                if message.kind != "candidate_finding" or message.id in seen_candidates:
                    continue
                seen_candidates.add(message.id)
                finding = Finding.model_validate(message.payload["finding"])
                verdict = await self._verify_candidate(
                    finding,
                    message,
                    mailbox,
                    blackboard,
                    publisher,
                    budget,
                    deadline,
                    deferred,
                )
                if verdict.accepted:
                    if accepted_count >= self._max_findings:
                        verdict = Verdict(
                            finding_id=finding.id,
                            accepted=False,
                            verdict="insufficient_evidence",
                            confidence=verdict.confidence,
                            severity=None,
                            reason="最终 Finding 已达到八条保留上限，当前候选未纳入结果。",
                            final_finding=None,
                        )
                    else:
                        accepted_count += 1
                verdicts.append(verdict)
                await publisher.publish(
                    sender="verifier",
                    recipient="*",
                    kind="verdict",
                    key=f"verdict:{finding.id}",
                    payload={"verdict": verdict.model_dump(mode="json")},
                    correlation_id=finding.id,
                )
            await self._publish_terminal(
                publisher,
                failed=False,
                warning="Verifier 达到时间预算，已返回当前裁决。" if timed_out else None,
            )
            return verdicts
        except asyncio.CancelledError:
            await asyncio.shield(self._publish_terminal(publisher, failed=True, warning="Verifier 已取消。"))
            raise
        except Exception:
            await self._publish_terminal(publisher, failed=True, warning="Verifier 执行未完成。")
            raise

    async def _verify_candidate(
        self,
        finding: Finding,
        candidate_message: TeamMessage,
        mailbox: Mailbox,
        blackboard: EvidenceBlackboard,
        publisher: MessagePublisher,
        budget: Budget,
        watch_deadline: float,
        deferred: deque[TeamMessage],
    ) -> Verdict:
        """执行首次反证检查，并在证据不足时最多补证一次。"""

        first = await self._model_verdict(finding, budget, evidence_response=None)
        if first.verdict != "insufficient_evidence" or self._model is None:
            return self._normalize_verdict(first, finding)
        response = await self._request_evidence(
            finding,
            candidate_message,
            mailbox,
            blackboard,
            publisher,
            watch_deadline,
            deferred,
        )
        if response is None or response.conclusion == "uncertain":
            return self._normalize_verdict(first, finding)
        if response.conclusion == "withdrawn":
            return Verdict(
                finding_id=finding.id,
                accepted=False,
                verdict="false_positive",
                confidence=max(first.confidence, self._confidence_threshold),
                severity=None,
                reason=response.summary,
                final_finding=None,
            )
        second = await self._model_verdict(finding, budget, evidence_response=response)
        return self._normalize_verdict(second, finding)

    async def _model_verdict(
        self,
        finding: Finding,
        budget: Budget,
        *,
        evidence_response: EvidenceResponse | None,
    ) -> Verdict:
        """只向模型提供公开候选、代码证据和一次可选补证。"""

        if self._model is None:
            return Verdict(
                finding_id=finding.id,
                accepted=False,
                verdict="insufficient_evidence",
                confidence=0.0,
                reason="未配置 Verifier 模型，无法确认候选。",
            )
        registry = SkillRegistry(self._skills_root)
        dynamic_context = {
            "task": "尝试推翻该候选；只验证现有结论，不主动寻找新问题。",
            "candidate": finding.model_dump(mode="json"),
            "evidence_response": None if evidence_response is None else evidence_response.model_dump(mode="json"),
        }
        try:
            return await self._runtime.run_structured(
                self._model,
                role="verifier",
                sources=[
                    PromptSource("shared-system", Path(__file__).parent / "prompts" / "shared-system.md"),
                    PromptSource("verifier", Path(__file__).parent / "prompts" / "verifier.md"),
                ],
                skills=registry.select("verifier", [finding.category, "general"], budget),
                dynamic_context=json.dumps(dynamic_context, ensure_ascii=False),
                budget=budget,
                output_type=Verdict,
                tools=self._tools,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return Verdict(
                finding_id=finding.id,
                accepted=False,
                verdict="insufficient_evidence",
                confidence=0.0,
                reason="Verifier 未能生成有效的结构化裁决。",
            )

    async def _request_evidence(
        self,
        finding: Finding,
        candidate_message: TeamMessage,
        mailbox: Mailbox,
        blackboard: EvidenceBlackboard,
        publisher: MessagePublisher,
        watch_deadline: float,
        deferred: deque[TeamMessage],
    ) -> EvidenceResponse | None:
        """发送一次定向补证请求，并只消费关联响应。"""

        request = VerificationRequest(
            finding_id=finding.id,
            target_agent=finding.producer,
            question="请补充触发路径、上游保护和当前 PR 归因所需的结构化证据。",
            required_evidence=["触发入口", "修改行", "上游保护", "PR 归因"],
            deadline_seconds=30,
        )
        await publisher.publish(
            sender="verifier",
            recipient=candidate_message.sender,
            kind="verification_request",
            key=f"verification:{finding.id}",
            payload=request.model_dump(mode="json"),
            correlation_id=finding.id,
        )
        existing = self._find_evidence_response(blackboard.messages, finding.id)
        if existing is not None:
            return existing
        loop = asyncio.get_running_loop()
        response_deadline = min(watch_deadline, loop.time() + self._evidence_deadline_seconds)
        while loop.time() < response_deadline:
            try:
                message = await mailbox.receive_one("verifier", timeout=response_deadline - loop.time())
            except TimeoutError:
                return None
            if message.kind == "evidence_response" and self._matches_finding(message, finding.id):
                return EvidenceResponse.model_validate(message.payload)
            deferred.append(message)
        return None
    def _normalize_verdict(self, verdict: Verdict, finding: Finding) -> Verdict:
        """绑定真实候选，并执行最低置信度和最终 Finding 约束。"""

        accepted = (
            verdict.accepted
            and verdict.verdict in {"confirmed", "likely"}
            and verdict.confidence >= self._confidence_threshold
        )
        if not accepted:
            low_confidence = verdict.accepted and verdict.confidence < self._confidence_threshold
            return Verdict(
                finding_id=finding.id,
                accepted=False,
                verdict="insufficient_evidence" if low_confidence else verdict.verdict,
                confidence=verdict.confidence,
                severity=None,
                reason=(f"{verdict.reason} 最终置信度低于 0.6，未发布。" if low_confidence else verdict.reason),
                final_finding=None,
            )
        severity = verdict.severity or finding.severity
        final_finding = finding.model_copy(update={"confidence": verdict.confidence, "severity": severity})
        return Verdict(
            finding_id=finding.id,
            accepted=True,
            verdict=verdict.verdict,
            confidence=verdict.confidence,
            severity=severity,
            reason=verdict.reason,
            final_finding=final_finding,
        )

    async def _publish_terminal(
        self,
        publisher: MessagePublisher,
        *,
        failed: bool,
        warning: str | None,
    ) -> None:
        """发布唯一、可幂等的 Verifier 终态消息。"""

        kind = "agent_failed" if failed else "agent_completed"
        payload: dict[str, Any] = {"agent_id": "verifier", "role": "verifier"}
        if warning is not None:
            payload["warning"] = warning
        await publisher.publish(
            sender="verifier",
            recipient="*",
            kind=kind,
            key="failed" if failed else "completed",
            payload=payload,
        )

    @staticmethod
    def _terminal_role(message: TeamMessage) -> str | None:
        """从专家终态中提取冻结角色名。"""

        if message.kind not in {"agent_completed", "agent_failed"}:
            return None
        role = message.payload.get("role")
        return role if role in {"defect", "intent"} else None

    @classmethod
    def _terminal_roles(cls, messages: list[TeamMessage]) -> set[str]:
        """收集 watcher 启动前已经出现的专家终态。"""

        return {role for message in messages if (role := cls._terminal_role(message)) is not None}

    @staticmethod
    def _matches_finding(message: TeamMessage, finding_id: str) -> bool:
        """判断补证响应是否属于当前候选。"""

        return message.correlation_id == finding_id or message.payload.get("finding_id") == finding_id

    @classmethod
    def _find_evidence_response(
        cls,
        messages: list[TeamMessage],
        finding_id: str,
    ) -> EvidenceResponse | None:
        """从共享事实中寻找已到达的关联补证。"""

        for message in messages:
            if message.kind == "evidence_response" and cls._matches_finding(message, finding_id):
                return EvidenceResponse.model_validate(message.payload)
        return None
