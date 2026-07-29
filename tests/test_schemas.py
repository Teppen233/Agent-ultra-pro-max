"""审查领域模型测试。"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from reviewcrew.schemas import CodeEvidence, Finding, ReviewRequest


def make_finding(*, confidence: float = 0.8) -> Finding:
    """构造用于验证的最小候选问题。"""

    return Finding(
        id="finding-1",
        producer="defect",
        category="security",
        severity="high",
        confidence=confidence,
        file="src/auth.py",
        line_start=12,
        line_end=12,
        title="缺少资源归属校验",
        description="接口直接使用外部资源标识读取数据。",
        trigger_condition="攻击者提交其他用户的资源标识。",
        impact="攻击者可以读取其他用户的数据。",
        reasoning_summary="修改行移除了资源所有者校验。",
        suggestion="读取前校验资源所有者。",
        evidence=[
            CodeEvidence(
                source="diff",
                file="src/auth.py",
                start_line=12,
                end_line=12,
                description="修改后的查询未限制所有者。",
                content="return repo.get(resource_id)",
            )
        ],
        created_at=datetime.now(UTC),
    )


def test_finding_requires_confidence_in_range() -> None:
    """置信度必须位于零到一之间。"""

    with pytest.raises(ValidationError):
        make_finding(confidence=1.1)


def test_finding_requires_valid_line_range() -> None:
    """结束行不能小于开始行。"""

    finding = make_finding().model_dump()
    finding["line_start"] = 20
    finding["line_end"] = 10

    with pytest.raises(ValidationError):
        Finding.model_validate(finding)


def test_review_request_requires_exactly_one_mode() -> None:
    """审查请求只能选择一种输入模式。"""

    with pytest.raises(ValidationError):
        ReviewRequest(
            pr_url="https://github.com/acme/demo/pull/1",
            replay_run_id="run-1",
        )


def test_review_request_accepts_local_mode() -> None:
    """本地模式必须同时提供仓库、基准和目标引用。"""

    request = ReviewRequest(repo_path="D:/repo", base_ref="main", head_ref="feature")

    assert request.repo_path == "D:/repo"

