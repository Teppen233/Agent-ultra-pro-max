"""专家 Agent 测试 —— DefectAgent 和 IntentAgent 的 Fake Model 输出验证。"""

import pytest


@pytest.mark.asyncio
async def test_defect_agent_finds_security_issues():
    """DefectAgent 应能发现 SQL 注入风险。"""
    from reviewcrew.agents.defect import DefectAgent
    from reviewcrew.llm.glm import build_fake_model
    from reviewcrew.schemas import ContextPack, DiffHunk

    model = build_fake_model()
    agent = DefectAgent(model=model, agent_id="defect-1")

    context = ContextPack(
        id="pack-1",
        repository="test/repo",
        base_sha="abc",
        head_sha="def",
        files=["src/login.py"],
        diff_hunks=[
            DiffHunk(
                id="h1",
                file="src/login.py",
                old_start=10,
                old_count=3,
                new_start=10,
                new_count=4,
                changed_lines=[11, 12],
                content="+query = f\"SELECT * FROM users WHERE name='{username}'\"",
            )
        ],
        enclosing_code=[],
    )

    # DefectAgent 应从 Fake Model 获取结构化输出
    snapshot = await agent.run(context, None, None)  # type: ignore
    assert snapshot is not None
    assert snapshot.role == "defect"


@pytest.mark.asyncio
async def test_intent_agent_analyzes_business_logic():
    """IntentAgent 应能分析业务逻辑偏差。"""
    from reviewcrew.agents.intent import IntentAgent
    from reviewcrew.llm.glm import build_fake_model
    from reviewcrew.schemas import ContextPack, DiffHunk

    model = build_fake_model()
    agent = IntentAgent(model=model, agent_id="intent-1")

    context = ContextPack(
        id="pack-1",
        repository="test/repo",
        base_sha="abc",
        head_sha="def",
        pr_title="修复会员折扣计算",
        pr_description="VIP 会员应享受 8 折优惠",
        files=["src/pricing.py"],
        diff_hunks=[
            DiffHunk(
                id="h1",
                file="src/pricing.py",
                old_start=20,
                old_count=3,
                new_start=20,
                new_count=4,
                changed_lines=[22],
                content="+discount = 0.9  # 应该是 0.8",
            )
        ],
        enclosing_code=[],
    )

    snapshot = await agent.run(context, None, None)  # type: ignore
    assert snapshot is not None
    assert snapshot.role == "intent"
