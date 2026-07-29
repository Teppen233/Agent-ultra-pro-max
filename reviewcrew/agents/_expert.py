"""专家 Agent 共用的结构化运行与团队协作外壳。"""

from __future__ import annotations

from collections.abc import Sequence
import asyncio
import json
from pathlib import Path
from typing import Any, Literal

from pydantic_ai.models import Model

from reviewcrew.agents.base import AgentRuntime, PromptSource
from reviewcrew.config import Config
from reviewcrew.schemas import (
    AgentSnapshot,
    Budget,
    ContextPack,
    EvidenceResponse,
    Finding,
    HandoffAssessment,
    HandoffRequest,
    ReviewPlan,
    TeamMessage,
    VerificationRequest,
)
from reviewcrew.skills.registry import SkillRegistry
from reviewcrew.team.blackboard import EvidenceBlackboard
from reviewcrew.team.mailbox import Mailbox
from reviewcrew.team.publisher import MessagePublisher


Role = Literal["defect", "intent"]


class ExpertAgent:
    """将角色 Prompt、模型输出和公开安全的协作消息统一起来。"""

    role: Role

    def __init__(
        self,
        *,
        role: Role,
        model: Model | None = None,
        skills_root: Path | None = None,
        config: Config | None = None,
        runtime: AgentRuntime | None = None,
        tools: Sequence[Any] = (),
        publisher: MessagePublisher | None = None,
        collaboration_window_seconds: float | None = None,
        max_evidence_requests: int = 8,
    ) -> None:
        self.role = role
        self._model = model
        self._skills_root = skills_root or Path(__file__).parent.parent / "skills"
        self._config = config or Config()
        self._runtime = runtime or AgentRuntime(config=self._config)
        self._tools = tuple(tools)
        self._publisher = publisher
        self._collaboration_window_seconds = collaboration_window_seconds
        if max_evidence_requests <= 0:
            raise ValueError("补证请求总量上限必须大于零")
        self._max_evidence_requests = max_evidence_requests
        self._handled_handoffs: set[str] = set()
        self._handled_evidence: set[str] = set()

    async def run(
        self,
        context: ContextPack,
        mailbox: Mailbox | None = None,
        blackboard: EvidenceBlackboard | None = None,
        *,
        plan: ReviewPlan | None = None,
        budget: Budget | None = None,
    ) -> AgentSnapshot:
        """运行单个上下文分片，并发布候选、补证和终态消息。"""

        effective_budget = budget or Budget(seconds=plan.budget_seconds if plan is not None else 60)
        deadline = asyncio.get_running_loop().time() + effective_budget.seconds
        agent_id = f"{self.role}:{context.id}"
        self._handled_handoffs.clear()
        self._handled_evidence.clear()
        publisher = self._publisher or (MessagePublisher(mailbox=mailbox, blackboard=blackboard) if mailbox is not None or blackboard is not None else None)
        latest_snapshot = AgentSnapshot(
            agent_id=agent_id,
            pending_checks=self._checks(),
            warnings=["专家在预算边界前尚未完成模型审查。"],
        )
        try:
            snapshot = await self._review(context, agent_id, effective_budget)
            snapshot = self._normalize_snapshot(snapshot, context, agent_id)
            latest_snapshot = snapshot
            await self._publish_findings(snapshot, context, publisher)
            await self._respond_to_requests(
                snapshot, context, mailbox, blackboard, publisher, effective_budget, deadline
            )
            await self._consume_collaboration_window(
                snapshot, context, mailbox, publisher, effective_budget, deadline
            )
            await self._publish(
                context,
                publisher,
                kind="agent_completed",
                recipient="*",
                key="completed",
                payload={"agent_id": agent_id, "role": self.role, "context_id": context.id},
            )
            return snapshot
        except asyncio.CancelledError:
            await asyncio.shield(
                self._publish(
                    context,
                    publisher,
                    kind="agent_snapshot",
                    recipient="orchestrator",
                    key="snapshot",
                    payload={"snapshot": latest_snapshot.model_dump(mode="json")},
                )
            )
            await asyncio.shield(self._publish(context, publisher, kind="agent_failed", recipient="*", key="failed", payload={"agent_id": agent_id, "role": self.role, "context_id": context.id, "warning": "专家已取消。"}))
            raise
        except Exception:
            await self._publish(
                context,
                publisher,
                kind="agent_failed",
                recipient="*",
                key="failed",
                payload={
                    "agent_id": agent_id,
                    "role": self.role,
                    "context_id": context.id,
                    "warning": "专家执行未完成。",
                },
            )
            raise

    async def _review(self, context: ContextPack, agent_id: str, budget: Budget) -> AgentSnapshot:
        """调用模型；未配置模型时保守地返回空候选快照。"""

        if self._model is None:
            return AgentSnapshot(
                agent_id=agent_id,
                completed_checks=self._checks(),
                warnings=["未配置模型，未生成候选问题。"],
            )
        registry = SkillRegistry(self._skills_root)
        snapshot = await self._runtime.run_structured(
            self._model,
            role=self.role,
            sources=[
                PromptSource("shared-system", Path(__file__).parent / "prompts" / "shared-system.md"),
                PromptSource(self.role, Path(__file__).parent / "prompts" / f"{self.role}.md"),
            ],
            skills=registry.select(self.role, self._risk_tags(context), budget),
            dynamic_context=self._context_summary(context),
            budget=budget,
            output_type=AgentSnapshot,
            tools=self._tools,
        )
        return snapshot

    def _normalize_snapshot(self, snapshot: AgentSnapshot, context: ContextPack, agent_id: str) -> AgentSnapshot:
        """只保留当前上下文修改行上的、带证据的角色归属候选。"""

        findings: list[Finding] = []
        for finding in snapshot.findings:
            normalized = finding.model_copy(update={"producer": self.role})
            if self._is_changed_finding(normalized, context):
                findings.append(normalized)
        dropped = len(snapshot.findings) - len(findings)
        warnings = list(snapshot.warnings)
        if dropped:
            warnings.append("已忽略不位于当前修改行的候选问题。")
        return snapshot.model_copy(
            update={
                "agent_id": agent_id,
                "findings": findings,
                "completed_checks": list(dict.fromkeys([*self._checks(), *snapshot.completed_checks])),
                "warnings": warnings,
            }
        )

    async def _publish_findings(
        self,
        snapshot: AgentSnapshot,
        context: ContextPack,
        publisher: MessagePublisher | None,
    ) -> None:
        """把每个已验证结构的候选交给 Verifier，而不发布模型原文。"""

        for finding in snapshot.findings:
            await self._publish(
                context,
                publisher,
                kind="candidate_finding",
                recipient="verifier",
                key=f"candidate:{finding.id}",
                payload={"finding": finding.model_dump(mode="json"), "context_id": context.id},
                correlation_id=finding.id,
            )

    async def _respond_to_requests(
        self,
        snapshot: AgentSnapshot,
        context: ContextPack,
        mailbox: Mailbox | None,
        blackboard: EvidenceBlackboard | None,
        publisher: MessagePublisher | None,
        budget: Budget,
        deadline: float,
    ) -> None:
        """处理至多两项结构化移交，并对定向补证请求给出结构化响应。"""

        if blackboard is None:
            return
        agent_id = snapshot.agent_id
        for message in tuple(blackboard.messages):
            if message.kind == "handoff_request" and len(self._handled_handoffs) < 2 and message.id not in self._handled_handoffs:
                request = HandoffRequest.model_validate(message.payload)
                if request.target_agent != self.role:
                    continue
                self._handled_handoffs.add(message.id)
                assessment = await self._assess_handoff(request, context, budget, deadline)
                await self._publish(
                    context,
                    publisher,
                    kind="handoff_response",
                    recipient=request.source_agent,
                    key=f"handoff:{message.id}",
                    payload={
                        "agent_id": agent_id,
                        "role": self.role,
                        "context_id": context.id,
                        "hypothesis": request.hypothesis,
                        "requested_check": request.requested_check,
                        "conclusion": assessment.conclusion,
                        "reason": assessment.reason,
                        "evidence": [item.model_dump(mode="json") for item in assessment.evidence],
                    },
                    correlation_id=message.correlation_id or message.id,
                )
            if message.kind == "verification_request":
                request = VerificationRequest.model_validate(message.payload)
                if request.target_agent != self.role:
                    continue
                if request.finding_id in self._handled_evidence:
                    continue
                if len(self._handled_evidence) >= self._max_evidence_requests:
                    continue
                self._handled_evidence.add(request.finding_id)
                finding = next((item for item in snapshot.findings if item.id == request.finding_id), None)
                response = EvidenceResponse(
                    finding_id=request.finding_id,
                    conclusion="supported" if finding is not None else "uncertain",
                    evidence=[] if finding is None else finding.evidence,
                    summary="已提供当前上下文中的结构化证据。" if finding is not None else "当前上下文未发现对应候选。",
                )
                await self._publish(
                    context,
                    publisher,
                    kind="evidence_response",
                    recipient="verifier",
                    key=f"evidence:{request.finding_id}",
                    payload=response.model_dump(mode="json"),
                    correlation_id=message.correlation_id or request.finding_id,
                )

    async def _assess_handoff(
        self,
        request: HandoffRequest,
        context: ContextPack,
        budget: Budget,
        deadline: float,
    ) -> HandoffAssessment:
        """在共享请求和时间预算内执行一次仅面向目标行的结构化复查。"""

        target_evidence = [
            {
                "source": "diff",
                "file": hunk.file,
                "start_line": line,
                "end_line": line,
                "description": "定向检查命中的修改行。",
                "content": hunk.content,
            }
            for hunk in context.diff_hunks
            if hunk.file == request.file
            for line in hunk.changed_lines
            if line in request.lines
        ]
        if not target_evidence:
            return HandoffAssessment(conclusion="insufficient", reason="目标修改行没有可验证证据。")
        if self._model is None:
            return HandoffAssessment(conclusion="insufficient", reason="未配置可执行定向复查的模型。")
        request_budget = self._runtime.budget or budget
        if request_budget.remaining_requests <= 0:
            return HandoffAssessment(conclusion="insufficient", reason="共享模型请求预算不足，无法执行定向复查。")
        remaining_seconds = deadline - asyncio.get_running_loop().time()
        if remaining_seconds <= 0:
            return HandoffAssessment(conclusion="insufficient", reason="共享时间预算不足，无法执行定向复查。")

        dynamic_context = json.dumps(
            {
                "task": "仅执行 requested_check，判断目标行证据是否支持 hypothesis；不得扩展为完整代码审查。",
                "hypothesis": request.hypothesis,
                "requested_check": request.requested_check,
                "target": {"file": request.file, "lines": request.lines},
                "target_line_evidence": target_evidence,
            },
            ensure_ascii=False,
        )
        try:
            async with asyncio.timeout(remaining_seconds):
                assessment = await self._runtime.run_structured(
                    self._model,
                    role=self.role,
                    sources=[
                        PromptSource("shared-system", Path(__file__).parent / "prompts" / "shared-system.md")
                    ],
                    skills=[],
                    dynamic_context=dynamic_context,
                    budget=budget,
                    output_type=HandoffAssessment,
                    tools=self._tools,
                )
        except TimeoutError:
            return HandoffAssessment(conclusion="insufficient", reason="定向复查超过共享时间预算。")
        except Exception:
            return HandoffAssessment(conclusion="insufficient", reason="定向复查未能生成有效的结构化结论。")

        requested_lines = set(request.lines)
        verified_evidence = [
            item
            for item in assessment.evidence
            if item.source == "diff"
            and item.file == request.file
            and any(item.start_line <= line <= item.end_line for line in requested_lines)
        ]
        if assessment.conclusion != "insufficient" and not verified_evidence:
            return HandoffAssessment(conclusion="insufficient", reason="定向复查结论缺少目标修改行证据。")
        return assessment.model_copy(update={"evidence": verified_evidence})

    async def _consume_collaboration_window(
        self,
        snapshot: AgentSnapshot,
        context: ContextPack,
        mailbox: Mailbox | None,
        publisher: MessagePublisher | None,
        budget: Budget,
        deadline: float,
    ) -> None:
        """在明确且有界的窗口内处理候选发布后到达的定向请求。"""

        if mailbox is None:
            return
        mailbox.register(snapshot.agent_id)
        loop = asyncio.get_running_loop()
        if self._collaboration_window_seconds is not None:
            deadline = min(deadline, loop.time() + self._collaboration_window_seconds)
        while loop.time() < deadline and (
            len(self._handled_handoffs) < 2
            or len(self._handled_evidence) < self._max_evidence_requests
        ):
            try:
                message = await mailbox.receive_one(snapshot.agent_id, timeout=max(0.0, deadline - loop.time()))
            except TimeoutError:
                break
            if message.kind not in {"handoff_request", "verification_request"}:
                continue
            board = EvidenceBlackboard(message.run_id, messages=[message])
            await self._respond_to_requests(snapshot, context, mailbox, board, publisher, budget, deadline)

    async def _publish(
        self,
        context: ContextPack,
        publisher: MessagePublisher | None,
        *,
        kind: Literal["candidate_finding", "handoff_response", "evidence_response", "agent_snapshot", "agent_completed", "agent_failed"],
        recipient: str,
        key: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
    ) -> None:
        """向可用协作设施提交同一条可序列化、安全摘要消息。"""

        if publisher is None:
            return
        await publisher.publish(sender=f"{self.role}:{context.id}", recipient=recipient, kind=kind, key=key, payload=payload, correlation_id=correlation_id)

    @staticmethod
    def _is_changed_finding(finding: Finding, context: ContextPack) -> bool:
        """确认候选定位到本分片中实际修改的文件和行。"""

        return any(
            hunk.file == finding.file
            and any(finding.line_start <= line <= finding.line_end for line in hunk.changed_lines)
            for hunk in context.diff_hunks
        ) and any(
            evidence.source == "diff" and evidence.file == finding.file
            and any(evidence.start_line <= line <= evidence.end_line for hunk in context.diff_hunks if hunk.file == evidence.file for line in hunk.changed_lines)
            for evidence in finding.evidence
        )

    @staticmethod
    def _risk_tags(context: ContextPack) -> list[str]:
        """从上下文的公开字段提取 Skill 选择所需的最小风险标签。"""

        text = "\n".join([context.pr_title, context.pr_description, *(hunk.content for hunk in context.diff_hunks)]).lower()
        risks = ["security"] if any(word in text for word in ("sql", "auth", "token", "权限", "鉴权")) else []
        return risks or ["general"]

    @staticmethod
    def _context_summary(context: ContextPack) -> str:
        """向模型提供任务所需的上下文，不持久化 Prompt 或模型响应。"""

        return context.model_dump_json()

    def _checks(self) -> list[str]:
        """由具体专家声明完成的稳定检查名称。"""

        raise NotImplementedError
