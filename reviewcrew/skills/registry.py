"""读取版本化 Skill 并按角色、风险和预算选择。"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import yaml

from reviewcrew.agents.base import Budget


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    """一个带 YAML 元数据的 Markdown Skill。"""

    name: str
    version: str
    roles: tuple[str, ...]
    risks: tuple[str, ...]
    estimated_seconds: int
    priority: int
    content: str
    content_hash: str
    path: Path


class SkillRegistry:
    """从本地 Markdown 加载 Skill，并保持 Prompt 构建可复现。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._skills = self._load()

    def select(self, role: str, risks: list[str], budget: Budget) -> list[SkillDefinition]:
        """选择角色可用、命中风险且不超预算的 Skill。"""

        selected: list[SkillDefinition] = []
        spent = 0
        risk_set = set(risks)
        candidates = sorted(
            self._skills,
            key=lambda skill: (role not in skill.roles, skill.priority, skill.name),
        )
        for skill in candidates:
            if role not in skill.roles:
                continue
            if skill.risks and not risk_set.intersection(skill.risks):
                continue
            if spent + skill.estimated_seconds > budget.seconds:
                continue
            selected.append(skill)
            spent += skill.estimated_seconds
        return selected

    @staticmethod
    def compose_prompt(
        *,
        shared_rule: str,
        role_prompt: str,
        skills: list[SkillDefinition],
        dynamic_context: str,
        remaining_budget: int,
        output_schema: str,
    ) -> str:
        """按固定顺序组装共享规则、角色、Skill、动态数据、预算和 Schema。"""

        skill_text = "\n\n".join(skill.content for skill in skills)
        return "\n\n".join(
            (
                shared_rule,
                role_prompt,
                skill_text,
                dynamic_context,
                f"剩余预算：{remaining_budget} 秒",
                f"输出 Schema：{output_schema}",
            )
        )

    @staticmethod
    def prompt_hash(prompt: str) -> str:
        """返回 Prompt 的稳定 SHA-256 哈希。"""

        return sha256(prompt.encode("utf-8")).hexdigest()

    def _load(self) -> list[SkillDefinition]:
        """加载所有带 YAML 前置元数据的 Markdown Skill。"""

        skills: list[SkillDefinition] = []
        for path in sorted(self.root.rglob("*.md")):
            if path.name.startswith("."):
                continue
            content = path.read_text(encoding="utf-8")
            metadata, body = self._parse_front_matter(content, path)
            skills.append(
                SkillDefinition(
                    name=str(metadata["name"]),
                    version=str(metadata["version"]),
                    roles=tuple(metadata.get("roles", [])),
                    risks=tuple(metadata.get("risks", [])),
                    estimated_seconds=int(metadata.get("estimated_seconds", 0)),
                    priority=int(metadata.get("priority", 100)),
                    content=body.strip(),
                    content_hash=sha256(content.encode("utf-8")).hexdigest(),
                    path=path,
                )
            )
        return skills

    @staticmethod
    def _parse_front_matter(content: str, path: Path) -> tuple[dict[str, object], str]:
        """校验并拆分 YAML 前置元数据。"""

        if not content.startswith("---\n"):
            raise ValueError(f"Skill 缺少 YAML 元数据：{path}")
        _, metadata_text, body = content.split("---\n", 2)
        metadata = yaml.safe_load(metadata_text)
        if not isinstance(metadata, dict) or "name" not in metadata or "version" not in metadata:
            raise ValueError(f"Skill YAML 元数据不完整：{path}")
        return metadata, body
