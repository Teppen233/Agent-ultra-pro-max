"""流式消费候选并寻找反证的 Verifier Agent。"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any, Sequence

from pydantic_ai.models import Model

from reviewcrew.agents.base import AgentRuntime, PromptSource, resolve_role_model
from reviewcrew.config import Config
from reviewcrew.schemas import (
    Budget,
    CodeEvidence,
    EvidenceResponse,
    Finding,
    TeamMessage,
    Verdict,
    VerificationRequest,
)
from reviewcrew.skills.registry import SkillRegistry
from reviewcrew.team.blackboard import EvidenceBlackboard
from reviewcrew.team.mailbox import Mailbox
from reviewcrew.team.publisher import MessagePublisher


class _VerifierDeadlineExceeded(TimeoutError):
    """表示模型调用已耗尽 watcher 的绝对时间预算。"""


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
        self._skills_root = skills_root or Path(__file__).parent.parent / "skills"
        self._config = config or Config()
        self._model = resolve_role_model(model, self._config, "verifier")
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
        *,
        expected_agent_ids: set[str] | None = None,
        stop_event: asyncio.Event | None = None,
    ) -> list[Verdict]:
        """监听候选消息，并按实例终态、显式停止或预算截止收敛。"""

        mailbox.register("verifier")
        publisher = self._publisher or MessagePublisher(mailbox=mailbox, blackboard=blackboard)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + budget.seconds
        deferred: deque[TeamMessage] = deque()
        seen_finding_ids: set[str] = set()
        expected = None if expected_agent_ids is None else set(expected_agent_ids)
        terminal_agent_ids = self._terminal_agent_ids(blackboard.messages)
        verdicts: list[Verdict] = []
        accepted_count = 0
        timed_out = False
        try:
            for message in tuple(blackboard.by_kind("candidate_finding")):
                deferred.append(message)
            while not self._should_stop(expected, terminal_agent_ids, stop_event, deferred):
                remaining = deadline - loop.time()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    message = (
                        deferred.popleft()
                        if deferred
                        else await self._receive_or_stop(
                            mailbox,
                            stop_event if expected is None else None,
                            remaining,
                        )
                    )
                except TimeoutError:
                    timed_out = True
                    break
                if message is None:
                    break
                if message.kind == "cancel":
                    await self._publish_terminal(publisher, failed=True, warning="Verifier 收到取消消息。")
                    return verdicts
                terminal_agent_id = self._terminal_agent_id(message)
                if terminal_agent_id is not None:
                    terminal_agent_ids.add(terminal_agent_id)
                    continue
                if message.kind != "candidate_finding":
                    continue
                finding = Finding.model_validate(message.payload["finding"])
                if finding.id in seen_finding_ids:
                    continue
                seen_finding_ids.add(finding.id)
                try:
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
                except _VerifierDeadlineExceeded:
                    timed_out = True
                    verdict = Verdict(
                        finding_id=finding.id,
                        accepted=False,
                        verdict="insufficient_evidence",
                        confidence=0.0,
                        severity=None,
                        reason="Verifier 模型调用超过共享时间预算，候选未发布。",
                        final_finding=None,
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
                if timed_out:
                    break
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

        verification_context = self._verification_context(candidate_message)
        first = await self._model_verdict(
            finding,
            budget,
            watch_deadline=watch_deadline,
            verification_context=verification_context,
            evidence_response=None,
        )
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
        enriched_finding = finding.model_copy(
            update={"evidence": self._merge_evidence(finding.evidence, response.evidence)}
        )
        second = await self._model_verdict(
            enriched_finding,
            budget,
            watch_deadline=watch_deadline,
            verification_context=verification_context,
            evidence_response=response,
        )
        return self._normalize_verdict(second, enriched_finding)

    async def _model_verdict(
        self,
        finding: Finding,
        budget: Budget,
        *,
        watch_deadline: float,
        verification_context: list[CodeEvidence],
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
            "necessary_context": [item.model_dump(mode="json") for item in verification_context],
            "evidence_response": None if evidence_response is None else evidence_response.model_dump(mode="json"),
        }
        remaining = watch_deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise _VerifierDeadlineExceeded
        try:
            async with asyncio.timeout(remaining):
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
        except TimeoutError as error:
            raise _VerifierDeadlineExceeded from error
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

        loop = asyncio.get_running_loop()
        available_seconds = min(
            self._evidence_deadline_seconds,
            max(0.0, watch_deadline - loop.time()),
        )
        deadline_seconds = min(30, int(available_seconds))
        if deadline_seconds <= 0:
            return None
        response_deadline = loop.time() + deadline_seconds
        expires_at = datetime.now(UTC) + timedelta(seconds=deadline_seconds)
        request = VerificationRequest(
            finding_id=finding.id,
            target_agent=finding.producer,
            question="请补充触发路径、上游保护和当前 PR 归因所需的结构化证据。",
            required_evidence=["触发入口", "修改行", "上游保护", "PR 归因"],
            deadline_seconds=deadline_seconds,
        )
        await publisher.publish(
            sender="verifier",
            recipient=candidate_message.sender,
            kind="verification_request",
            key=f"verification:{finding.id}",
            payload=request.model_dump(mode="json"),
            correlation_id=finding.id,
            expires_at=expires_at,
        )
        existing = self._find_evidence_response(blackboard.messages, finding.id)
        if existing is not None:
            return existing
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
    def _terminal_agent_id(message: TeamMessage) -> str | None:
        """从专家终态中提取完整实例标识。"""

        if message.kind not in {"agent_completed", "agent_failed"}:
            return None
        agent_id = message.payload.get("agent_id")
        return agent_id if isinstance(agent_id, str) and agent_id else message.sender

    @classmethod
    def _terminal_agent_ids(cls, messages: list[TeamMessage]) -> set[str]:
        """收集 watcher 启动前已经出现的实例终态。"""

        return {
            agent_id
            for message in messages
            if (agent_id := cls._terminal_agent_id(message)) is not None
        }

    @staticmethod
    def _should_stop(
        expected_agent_ids: set[str] | None,
        terminal_agent_ids: set[str],
        stop_event: asyncio.Event | None,
        deferred: deque[TeamMessage],
    ) -> bool:
        """判断实例终态或显式停止是否已满足，且无延后消息待处理。"""

        if deferred:
            return False
        if expected_agent_ids is not None:
            return expected_agent_ids.issubset(terminal_agent_ids)
        return stop_event is not None and stop_event.is_set()

    @staticmethod
    async def _receive_or_stop(
        mailbox: Mailbox,
        stop_event: asyncio.Event | None,
        timeout: float,
    ) -> TeamMessage | None:
        """等待下一条消息，同时允许调用方显式停止 watcher。"""

        if stop_event is None:
            return await mailbox.receive_one("verifier", timeout=timeout)
        receive_task = asyncio.create_task(mailbox.receive_one("verifier"))
        stop_task = asyncio.create_task(stop_event.wait())
        done, pending = await asyncio.wait(
            {receive_task, stop_task},
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise TimeoutError
        if receive_task in done:
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
            return receive_task.result()
        receive_task.cancel()
        await asyncio.gather(receive_task, return_exceptions=True)
        return None

    @staticmethod
    def _matches_finding(message: TeamMessage, finding_id: str) -> bool:
        """判断补证响应是否属于当前候选。"""

        return message.correlation_id == finding_id or message.payload.get("finding_id") == finding_id

    @staticmethod
    def _merge_evidence(
        original: list[CodeEvidence],
        supplemental: list[CodeEvidence],
    ) -> list[CodeEvidence]:
        """按完整结构键确定性合并原始证据与补证证据。"""

        by_key = {
            (
                item.source,
                item.file,
                item.start_line,
                item.end_line,
                item.description,
                item.content,
                item.content_hash or "",
            ): item
            for item in [*original, *supplemental]
        }
        return [by_key[key] for key in sorted(by_key)]

    @classmethod
    def _verification_context(cls, message: TeamMessage) -> list[CodeEvidence]:
        """只接收候选载荷中显式允许的类型化必要上下文。"""

        validated: list[CodeEvidence] = []
        raw_context = message.payload.get("verification_context", [])
        if not isinstance(raw_context, list):
            return validated
        for item in raw_context[:12]:
            try:
                validated.append(CodeEvidence.model_validate(item))
            except (TypeError, ValueError):
                continue
        return cls._merge_evidence([], validated)

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
