"""Skill Registry —— 可组合的审查方法模块加载和选择。

每个 Skill 使用 Markdown 加 YAML front matter 保存。
SkillRegistry 根据角色、风险标签和剩余预算选择合适的 Skill。
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class SkillDefinition:
    """Skill 元数据定义。"""

    name: str
    version: str
    roles: list[str]
    categories: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    max_tool_calls: int = 5
    body: str = ""  # Markdown 正文


class SkillRegistry:
    """Skill 注册表 —— 加载、选择和管理审查方法模块。"""

    def __init__(self, skills_dir: str | Path = "") -> None:
        self._skills: dict[str, SkillDefinition] = {}
        self._skills_dir = Path(skills_dir) if skills_dir else Path(__file__).parent
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """确保 Skills 已加载（懒加载）。"""
        if self._loaded:
            return
        self._loaded = True

        if not self._skills_dir.exists():
            return

        # 递归扫描 .md 文件
        for md_file in self._skills_dir.rglob("*.md"):
            try:
                skill = self._parse_skill_file(md_file)
                if skill:
                    self._skills[skill.name] = skill
            except Exception as e:
                logger.warning("解析 Skill 文件失败 %s: %s", md_file, e)

    def _parse_skill_file(self, path: Path) -> SkillDefinition | None:
        """解析单个 Skill Markdown 文件。

        期望格式：YAML front matter 后跟 Markdown 正文。
        """
        content = path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return None

        parts = content.split("---", 2)
        if len(parts) < 3:
            return None

        front_matter = yaml.safe_load(parts[1])
        if not isinstance(front_matter, dict):
            return None

        body = parts[2].strip()

        return SkillDefinition(
            name=front_matter.get("name", path.stem),
            version=str(front_matter.get("version", "0.1.0")),
            roles=front_matter.get("roles", []),
            categories=front_matter.get("categories", []),
            required_tools=front_matter.get("required_tools", []),
            max_tool_calls=front_matter.get("max_tool_calls", 5),
            body=body,
        )

    def select(
        self,
        role: str,
        risks: list[str] | None = None,
    ) -> list[SkillDefinition]:
        """为指定角色选择适用的 Skill。

        Args:
            role: Agent 角色（defect, intent, verifier, team_lead）
            risks: 风险标签列表，用于筛选相关类别

        Returns:
            匹配的 Skill 定义列表
        """
        self._ensure_loaded()

        selected = []
        for skill in self._skills.values():
            if role not in skill.roles and "all" not in skill.roles:
                continue
            if risks and skill.categories:
                if not any(r in skill.categories for r in risks):
                    continue
            selected.append(skill)

        return selected

    def get(self, name: str) -> SkillDefinition | None:
        """按名称获取 Skill。"""
        self._ensure_loaded()
        return self._skills.get(name)

    def list_all(self) -> list[str]:
        """列出所有已加载 Skill 名称。"""
        self._ensure_loaded()
        return sorted(self._skills.keys())

    def hash_prompt(self, skills: list[SkillDefinition]) -> str:
        """计算选定 Skills 的版本哈希，用于迭代追踪。"""
        content = "|".join(
            f"{s.name}:{s.version}" for s in sorted(skills, key=lambda x: x.name)
        )
        return hashlib.sha256(content.encode()).hexdigest()[:12]
