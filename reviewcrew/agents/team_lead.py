"""只负责审查计划的 Team Lead Agent。"""

from __future__ import annotations

from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models import Model

from reviewcrew.agents.base import Budget
from reviewcrew.schemas import ContextPack, PRData, ReviewPlan
from reviewcrew.skills.registry import SkillRegistry


class TeamLeadAgent:
    """为 PR 路由专家、上下文分片和预算，但从不生成 Finding。"""

    def __init__(self, model: Model | None = None, skills_root: Path | None = None) -> None:
        self._model = model
        self._skills_root = skills_root or Path(__file__).parent.parent / "skills"

    async def plan(self, pr: PRData, contexts: list[ContextPack], budget: Budget) -> ReviewPlan:
        """生成并规范化审查计划。"""

        risk_tags = self._detect_risks(pr, contexts)
        required_agents = ["defect", "intent"] if "security" in risk_tags else ["defect"]
        shards = self._build_shards(contexts, required_agents, budget, pr)
        fallback = ReviewPlan(
            summary=f"针对 {len(contexts)} 个上下文执行审查。",
            risk_tags=risk_tags,
            required_agents=required_agents,
            context_ids=[context.id for context in contexts],
            shards=shards,
            budget_seconds=budget.seconds,
        )
        if self._model is None:
            return fallback

        registry = SkillRegistry(self._skills_root)
        selected = registry.select("team_lead", risk_tags, budget)
        prompt = registry.compose_prompt(
            shared_rule=self._read_prompt("shared-system.md"),
            role_prompt=self._read_prompt("team-lead.md"),
            skills=selected,
            dynamic_context=f"PR：{pr.title}\n上下文：{', '.join(fallback.context_ids)}",
            remaining_budget=budget.seconds,
            output_schema="ReviewPlan",
        )
        result = await Agent(self._model, output_type=ReviewPlan, retries=1).run(prompt)
        return self._normalize_plan(result.output, fallback)

    def _normalize_plan(self, proposed: ReviewPlan, fallback: ReviewPlan) -> ReviewPlan:
        """强制安全路由、上下文边界和预算边界。"""

        required_agents = list(proposed.required_agents)
        if "security" in fallback.risk_tags:
            required_agents = ["defect", "intent"]
        return proposed.model_copy(
            update={
                "risk_tags": list(dict.fromkeys([*fallback.risk_tags, *proposed.risk_tags])),
                "required_agents": required_agents,
                "context_ids": fallback.context_ids,
                "shards": fallback.shards,
                "budget_seconds": fallback.budget_seconds,
            }
        )

    @staticmethod
    def _detect_risks(pr: PRData, contexts: list[ContextPack]) -> list[str]:
        """从差异与静态信号提取可解释的最小风险标签。"""

        text = "\n".join([pr.title, pr.description, pr.raw_diff, *(" ".join(item.files) for item in contexts)]).lower()
        risks: list[str] = []
        if any(token in text for token in ("auth", "token", "permission", "权限", "鉴权", "安全", "secret")):
            risks.append("security")
        if len(pr.files) >= 10 or len(pr.raw_diff) >= 20_000:
            risks.append("large_pr")
        return risks or ["general"]

    @staticmethod
    def _build_shards(
        contexts: list[ContextPack],
        agents: list[str],
        budget: Budget,
        pr: PRData,
    ) -> dict[str, list[str]]:
        """为已存在的上下文分片；预算不足时绝不扩展新分片。"""

        context_ids = [context.id for context in contexts]
        if not context_ids:
            return {agent: [] for agent in agents}
        if (len(pr.files) >= 10 or len(pr.raw_diff) >= 20_000) and budget.can_expand_shards:
            return {agent: list(context_ids) for agent in agents}
        return {agent: list(context_ids) for agent in agents}

    def _read_prompt(self, name: str) -> str:
        """读取版本化 Prompt 文件。"""

        return (Path(__file__).parent / "prompts" / name).read_text(encoding="utf-8")
