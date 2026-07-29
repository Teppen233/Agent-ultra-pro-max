"""只负责审查计划的 Team Lead Agent。"""

from __future__ import annotations

from pathlib import Path

from pydantic_ai.models import Model

from reviewcrew.agents.base import AgentRuntime, Budget, PromptSource
from reviewcrew.config import Config
from reviewcrew.schemas import ContextPack, PRData, ReviewPlan
from reviewcrew.skills.registry import SkillRegistry


class TeamLeadAgent:
    """为 PR 路由专家、上下文分片和预算，但从不生成 Finding。"""

    def __init__(
        self,
        model: Model | None = None,
        skills_root: Path | None = None,
        config: Config | None = None,
        runtime: AgentRuntime | None = None,
    ) -> None:
        self._model = model
        self._skills_root = skills_root or Path(__file__).parent.parent / "skills"
        self._config = config or Config()
        self._runtime = runtime or AgentRuntime(config=self._config)

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
        proposed = await self._runtime.run_structured(
            self._model,
            role="team_lead",
            sources=[
                PromptSource("shared-system", Path(__file__).parent / "prompts" / "shared-system.md"),
                PromptSource("team-lead", Path(__file__).parent / "prompts" / "team-lead.md"),
            ],
            skills=selected,
            dynamic_context=self._context_summary(pr, contexts, fallback.context_ids),
            budget=budget,
            output_type=ReviewPlan,
        )
        return self._normalize_plan(proposed, fallback)

    def _normalize_plan(self, proposed: ReviewPlan, fallback: ReviewPlan) -> ReviewPlan:
        """强制安全路由、上下文边界和预算边界。"""

        required_agents = list(dict.fromkeys(["defect", *proposed.required_agents]))
        if "security" in fallback.risk_tags and "intent" not in required_agents:
            required_agents.append("intent")
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
            shards: dict[str, list[str]] = {}
            for agent in agents:
                for context in contexts:
                    semantic_name = TeamLeadAgent._semantic_name(context)
                    shards.setdefault(f"{agent}:{semantic_name}", []).append(context.id)
            return shards
        return {agent: list(context_ids) for agent in agents}

    @staticmethod
    def _semantic_name(context: ContextPack) -> str:
        """从变更文件生成确定性的模块语义标签。"""

        if context.files:
            return Path(context.files[0]).stem.replace(" ", "-")
        return context.id

    @staticmethod
    def _context_summary(pr: PRData, contexts: list[ContextPack], context_ids: list[str]) -> str:
        """为规划模型提供不含代码正文的上下文摘要。"""

        summary = [f"PR：{pr.title}", f"上下文数量：{len(context_ids)}"]
        summary.extend(
            f"上下文 {context.id}：文件 {', '.join(context.files)}；差异块 {len(context.diff_hunks)}"
            for context in contexts
        )
        return "\n".join(summary)

    def _read_prompt(self, name: str) -> str:
        """读取版本化 Prompt 文件。"""

        return (Path(__file__).parent / "prompts" / name).read_text(encoding="utf-8")
