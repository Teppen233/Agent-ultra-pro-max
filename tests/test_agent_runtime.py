"""Agent 运行时与 Hooks 测试。"""

import pytest


# ---- LLM Model ----

def test_build_model_requires_api_key(monkeypatch):
    """缺少 API Key 时应抛出明确错误。"""
    monkeypatch.setenv("LLM_API_KEY", "")
    from reviewcrew.config import Config
    from reviewcrew.llm.glm import build_model

    config = Config.from_env()
    with pytest.raises(ValueError, match="API_KEY|API Key"):
        build_model(config)


def test_build_fake_model_works():
    """Fake Model 应始终可用。"""
    from reviewcrew.llm.glm import build_fake_model

    model = build_fake_model()
    assert model is not None


# ---- Hooks ----

def test_hook_manager_runs_registered_hooks():
    """注册的 Hook 应被正常触发。"""
    from reviewcrew.hooks import HookManager, HookContext

    manager = HookManager()
    results = []

    manager.register("before_run", lambda ctx: results.append("ran"))

    manager.run("before_run", HookContext(run_id="test"))
    assert results == ["ran"]


def test_hook_manager_non_security_errors_are_suppressed():
    """非安全 Hook 异常不应阻塞主管道。"""
    from reviewcrew.hooks import HookManager, HookContext

    manager = HookManager()

    def failing_hook(ctx):
        raise RuntimeError("测试异常")

    manager.register("after_agent", failing_hook)
    # 不应抛异常
    manager.run("after_agent", HookContext())


def test_hook_manager_security_errors_are_raised():
    """安全 Hook 异常必须传播。"""
    from reviewcrew.hooks import HookManager, HookContext

    manager = HookManager()

    def security_check(ctx):
        raise ValueError("安全校验失败")

    manager.register("before_tool_security", security_check)
    with pytest.raises(ValueError, match="安全校验失败"):
        manager.run("before_tool_security", HookContext())


# ---- Skill Registry ----

def test_skill_registry_parses_markdown_files():
    """Skill Registry 应正确解析 YAML front matter 的 MD 文件。"""
    from reviewcrew.skills.registry import SkillRegistry

    registry = SkillRegistry()
    skills = registry.list_all()

    # 至少有共享 Skill
    assert len(skills) >= 4
    assert "diff-first-review" in skills


def test_skill_registry_selects_by_role():
    """按角色选择应返回匹配的 Skill。"""
    from reviewcrew.skills.registry import SkillRegistry

    registry = SkillRegistry()
    defect_skills = registry.select("defect")
    defect_names = {s.name for s in defect_skills}

    assert "static-breakage" in defect_names
    assert "trace-untrusted-input" in defect_names


def test_skill_registry_selects_by_risk():
    """按风险标签筛选 Skill。"""
    from reviewcrew.skills.registry import SkillRegistry

    registry = SkillRegistry()
    security_skills = registry.select("defect", risks=["security"])

    names = {s.name for s in security_skills}
    assert "trace-untrusted-input" in names


def test_skill_hash_is_stable():
    """Skill 版本哈希应对相同 Skill 组合稳定。"""
    from reviewcrew.skills.registry import SkillRegistry

    registry = SkillRegistry()
    skills = registry.select("defect")
    h1 = registry.hash_prompt(skills)
    h2 = registry.hash_prompt(skills)
    assert h1 == h2
    assert len(h1) == 12
