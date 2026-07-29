"""候选问题确定性去重测试。"""

from datetime import UTC, datetime

from reviewcrew.pipeline.dedupe import deduplicate_findings
from reviewcrew.schemas import CodeEvidence, Finding


def make_evidence(*, source: str, line: int, description: str) -> CodeEvidence:
    """构造一条可稳定比较的代码证据。"""

    return CodeEvidence(
        source=source,
        file="src/service.py",
        start_line=line,
        end_line=line,
        description=description,
        content=f"line {line}",
    )


def make_finding(
    finding_id: str,
    *,
    line_start: int,
    line_end: int,
    confidence: float,
    category: str = "security",
    trigger_condition: str = "未经校验的外部输入到达 SQL 拼接点",
    evidence: list[CodeEvidence] | None = None,
) -> Finding:
    """构造覆盖去重关键字段的候选问题。"""

    return Finding(
        id=finding_id,
        producer="defect",
        category=category,
        severity="high",
        confidence=confidence,
        file="src/service.py",
        line_start=line_start,
        line_end=line_end,
        title=f"候选 {finding_id}",
        description="目标代码在特定输入下产生错误行为。",
        trigger_condition=trigger_condition,
        impact="请求可能失败。",
        reasoning_summary="候选直接位于修改行。",
        evidence=evidence or [make_evidence(source="diff", line=line_start, description=finding_id)],
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )


def test_deduplicate_merges_only_same_mechanism_and_keeps_strongest_candidate() -> None:
    """同文件重叠行、同类别、同触发机制才合并，并保留最高置信度候选。"""

    shared = make_evidence(source="diff", line=12, description="共享修改行")
    weaker = make_finding(
        "finding-b",
        line_start=10,
        line_end=12,
        confidence=0.72,
        evidence=[shared, make_evidence(source="search_code", line=20, description="调用入口")],
    )
    stronger = make_finding(
        "finding-a",
        line_start=12,
        line_end=14,
        confidence=0.93,
        trigger_condition="  未经校验的外部输入到达 SQL 拼接点  ",
        evidence=[make_evidence(source="git_show", line=12, description="本次变更"), shared],
    )

    result = deduplicate_findings([weaker, stronger])

    assert len(result) == 1
    assert result[0].id == "finding-a"
    assert result[0].confidence == 0.93
    assert [(item.source, item.start_line) for item in result[0].evidence] == [
        ("diff", 12),
        ("git_show", 12),
        ("search_code", 20),
    ]


def test_deduplicate_does_not_merge_different_trigger_mechanisms() -> None:
    """同一行上的不同触发机制不得因位置相同而误合并。"""

    unvalidated_input = make_finding("finding-input", line_start=10, line_end=12, confidence=0.9)
    missing_authorization = make_finding(
        "finding-auth",
        line_start=11,
        line_end=11,
        confidence=0.8,
        trigger_condition="已登录用户绕过资源归属校验",
    )

    assert {item.id for item in deduplicate_findings([unvalidated_input, missing_authorization])} == {
        "finding-auth",
        "finding-input",
    }


def test_deduplicate_is_independent_of_input_order() -> None:
    """输入顺序变化不得改变代表候选或证据顺序。"""

    first = make_finding("finding-z", line_start=30, line_end=32, confidence=0.8)
    second = make_finding(
        "finding-a",
        line_start=31,
        line_end=33,
        confidence=0.8,
        evidence=[make_evidence(source="read_file_range", line=31, description="保护分支")],
    )

    forward = [item.model_dump(mode="json") for item in deduplicate_findings([first, second])]
    backward = [item.model_dump(mode="json") for item in deduplicate_findings([second, first])]

    assert forward == backward
    assert forward[0]["id"] == "finding-a"
