"""Skill 元数据、选择和 Prompt 组装测试。"""

from pathlib import Path

from reviewcrew.agents.base import Budget
from reviewcrew.skills.registry import SkillRegistry


def test_skill_metadata_selection_prompt_order_and_stable_hash() -> None:
    """Skill 读取 YAML 元数据，Prompt 顺序固定且哈希稳定。"""

    root = Path(__file__).parents[1] / "reviewcrew" / "skills"
    registry = SkillRegistry(root)

    selected = registry.select("team_lead", ["security"], Budget(seconds=60))
    prompt = registry.compose_prompt(
        shared_rule="共享规则",
        role_prompt="角色提示",
        skills=selected,
        dynamic_context="计划上下文",
        remaining_budget=60,
        output_schema="ReviewPlan",
    )

    assert selected[0].name == "risk-routing"
    assert selected[0].version
    assert prompt.index("共享规则") < prompt.index("角色提示") < prompt.index("风险路由")
    assert registry.prompt_hash(prompt) == registry.prompt_hash(prompt)


def test_skill_content_change_changes_recorded_hash(tmp_path: Path) -> None:
    """Skill 内容或版本变化时哈希必须改变。"""

    first = tmp_path / "first.md"
    first.write_text("---\nname: demo\nversion: '1'\nroles: [team_lead]\n---\n规则一", encoding="utf-8")

    first_skill = SkillRegistry(tmp_path)._skills[0]
    first.write_text("---\nname: demo\nversion: '2'\nroles: [team_lead]\n---\n规则二", encoding="utf-8")
    second_skill = SkillRegistry(tmp_path)._skills[0]

    assert first_skill.content_hash != second_skill.content_hash
