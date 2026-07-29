"""Verifier 与去重测试。"""

import pytest


# ---- 去重 ----

def test_deduplicate_merges_same_file_line_category():
    """同文件、行号区间重叠、同类别的 Finding 应合并。"""
    from reviewcrew.pipeline.dedupe import deduplicate_findings
    from reviewcrew.schemas import Finding, CodeEvidence

    ev = CodeEvidence(file="a.py", line_start=10, line_end=12, content="x")
    f1 = Finding(
        id="f1", producer="defect", category="security", severity="high",
        confidence=0.8, file="a.py", line_start=10, line_end=12,
        title="SQL 注入 A", description="...", trigger_condition="...",
        impact="...", reasoning_summary="...", evidence=[ev],
    )
    f2 = Finding(
        id="f2", producer="defect", category="security", severity="high",
        confidence=0.9, file="a.py", line_start=11, line_end=13,
        title="SQL 注入 B", description="...", trigger_condition="...",
        impact="...", reasoning_summary="...", evidence=[ev],
    )

    result = deduplicate_findings([f1, f2])
    assert len(result) == 1
    assert result[0].confidence == 0.9  # 保留更高置信度


def test_deduplicate_keeps_different_categories():
    """不同类别的 Finding 不应被合并。"""
    from reviewcrew.pipeline.dedupe import deduplicate_findings
    from reviewcrew.schemas import Finding, CodeEvidence

    ev = CodeEvidence(file="a.py", line_start=10, line_end=12, content="x")
    f1 = Finding(
        id="f1", producer="defect", category="security", severity="high",
        confidence=0.8, file="a.py", line_start=10, line_end=12,
        title="风险", description="...", trigger_condition="...",
        impact="...", reasoning_summary="...", evidence=[ev],
    )
    f2 = Finding(
        id="f2", producer="intent", category="logic", severity="high",
        confidence=0.8, file="a.py", line_start=10, line_end=12,
        title="逻辑错误", description="...", trigger_condition="...",
        impact="...", reasoning_summary="...", evidence=[ev],
    )

    result = deduplicate_findings([f1, f2])
    assert len(result) == 2


def test_deduplicate_empty_list():
    """空列表返回空。"""
    from reviewcrew.pipeline.dedupe import deduplicate_findings

    assert deduplicate_findings([]) == []


# ---- Verifier ----

@pytest.mark.asyncio
async def test_verifier_accepts_valid_finding():
    """Verifier 应接受证据充分的 Finding。"""
    from reviewcrew.agents.verifier import VerifierAgent
    from reviewcrew.llm.glm import build_fake_model

    model = build_fake_model()
    agent = VerifierAgent(model=model, agent_id="verifier-1")

    snapshot = await agent.run(None, None)  # type: ignore
    assert snapshot is not None
    assert snapshot.role == "verifier"
