"""专家 Agent 共用的结构化运行与团队协作外壳。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
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
    HandoffRequest,
    ReviewPlan,
    TeamMessage,
    VerificationRequest,
)
from reviewcrew.skills.registry import SkillRegistry
from reviewcrew.team.blackboard import EvidenceBlackboard
from reviewcrew.team.mailbox import Mailbox


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
    ) -> None:
        self.role = role
        self._model = model
        self._skills_root = skills_root or Path(__file__).parent.parent / "skills"
        self._config = config or Config()
        self._runtime = runtime or AgentRuntime(config=self._config)
        self._tools = tuple(tools)

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
        agent_id = f"{self.role}:{context.id}"
        try:
            snapshot = await self._review(context, agent_id, effective_budget)
            snapshot = self._normalize_snapshot(snapshot, context, agent_id)
            await self._publish_findings(snapshot, context, mailbox, blackboard)
            await self._respond_to_requests(snapshot, context, mailbox, blackboard)
            await self._publish(
                context,
                mailbox,
                blackboard,
                kind="agent_completed",
                recipient="*",
                key="completed",
                payload={"agent_id": agent_id, "role": self.role, "context_id": context.id},
            )
            return snapshot
        except Exception:
            await self._publish(
                context,
                mailbox,
                blackboard,
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
        mailbox: Mailbox | None,
        blackboard: EvidenceBlackboard | None,
    ) -> None:
        """把每个已验证结构的候选交给 Verifier，而不发布模型原文。"""

        for finding in snapshot.findings:
            await self._publish(
                context,
                mailbox,
                blackboard,
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
    ) -> None:
        """处理至多两项结构化移交，并对定向补证请求给出结构化响应。"""

        if blackboard is None:
            return
        agent_id = snapshot.agent_id
        handoffs = 0
        for message in blackboard.messages:
            if message.kind == "handoff_request" and handoffs < 2:
                request = HandoffRequest.model_validate(message.payload)
                if request.target_agent != self.role:
                    continue
                handoffs += 1
                await self._publish(
                    context,
                    mailbox,
                    blackboard,
                    kind="handoff_response",
                    recipient=request.source_agent,
                    key=f"handoff:{message.id}",
                    payload={
                        "agent_id": agent_id,
                        "role": self.role,
                        "context_id": context.id,
                        "hypothesis": request.hypothesis,
                        "status": "received",
                    },
                    correlation_id=message.correlation_id or message.id,
                )
            if message.kind == "verification_request":
                request = VerificationRequest.model_validate(message.payload)
                if request.target_agent != self.role:
                    continue
                finding = next((item for item in snapshot.findings if item.id == request.finding_id), None)
                response = EvidenceResponse(
                    finding_id=request.finding_id,
                    conclusion="supported" if finding is not None else "uncertain",
                    evidence=[] if finding is None else finding.evidence,
                    summary="已提供当前上下文中的结构化证据。" if finding is not None else "当前上下文未发现对应候选。",
                )
                await self._publish(
                    context,
                    mailbox,
                    blackboard,
                    kind="evidence_response",
                    recipient="verifier",
                    key=f"evidence:{message.id}",
                    payload=response.model_dump(mode="json"),
                    correlation_id=message.correlation_id or request.finding_id,
                )

    async def _publish(
        self,
        context: ContextPack,
        mailbox: Mailbox | None,
        blackboard: EvidenceBlackboard | None,
        *,
        kind: Literal["candidate_finding", "handoff_response", "evidence_response", "agent_completed", "agent_failed"],
        recipient: str,
        key: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
    ) -> None:
        """向可用协作设施提交同一条可序列化、安全摘要消息。"""

        if mailbox is None and blackboard is None:
            return
        run_id = blackboard.run_id if blackboard is not None else mailbox.run_id  # type: ignore[union-attr]
        sequence = 1 if blackboard is None else max((item.sequence for item in blackboard.messages), default=0) + 1
        message = TeamMessage(
            id=f"{self.role}:{context.id}:{key}",
            run_id=run_id,
            sequence=sequence,
            timestamp=datetime.now(UTC),
            sender=f"{self.role}:{context.id}",
            recipient=recipient,
            kind=kind,
            correlation_id=correlation_id,
            payload=payload,
        )
        if blackboard is not None:
            blackboard.apply(message)
        if mailbox is not None:
            await mailbox.publish(message)

    @staticmethod
    def _is_changed_finding(finding: Finding, context: ContextPack) -> bool:
        """确认候选定位到本分片中实际修改的文件和行。"""

        return any(
            hunk.file == finding.file
            and any(finding.line_start <= line <= finding.line_end for line in hunk.changed_lines)
            for hunk in context.diff_hunks
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
