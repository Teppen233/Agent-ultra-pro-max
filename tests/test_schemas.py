"""领域模型测试 —— 校验所有公共 Pydantic Schema 的约束。"""

import pytest
from pydantic import ValidationError
from datetime import datetime, timezone


# ---- 辅助函数 ----

def make_finding(**overrides):
    """创建合法的 Finding 测试数据。"""
    from reviewcrew.schemas import Finding, CodeEvidence

    defaults = {
        "id": "f-001",
        "producer": "defect",
        "category": "security",
        "severity": "high",
        "confidence": 0.85,
        "file": "src/main.py",
        "line_start": 42,
        "line_end": 45,
        "title": "SQL 注入风险",
        "description": "用户输入未经过滤直接拼接到 SQL 查询中",
        "trigger_condition": "传入包含单引号的用户名",
        "impact": "攻击者可执行任意 SQL 语句",
        "reasoning_summary": "代码直接将用户输入拼入查询字符串",
        "suggestion": "使用参数化查询",
        "evidence": [
            CodeEvidence(
                file="src/main.py",
                line_start=42,
                line_end=45,
                content='query = "SELECT * FROM users WHERE name=\'" + username + "\'"',
                language="python",
            )
        ],
    }
    defaults.update(overrides)
    return Finding(**defaults)


# ---- ReviewRequest ----

def test_review_request_requires_exactly_one_mode():
    """pr_url、本地仓库参数和 replay_run_id 必须互斥。"""
    from reviewcrew.schemas import ReviewRequest

    # pr_url 和 replay_run_id 同时提供
    with pytest.raises(ValidationError):
        ReviewRequest(pr_url="https://github.com/a/b/pull/1", replay_run_id="run-1")

    # 三者都不提供
    with pytest.raises(ValidationError):
        ReviewRequest()


def test_review_request_accepts_pr_url():
    """仅提供 pr_url 应通过校验。"""
    from reviewcrew.schemas import ReviewRequest

    req = ReviewRequest(pr_url="https://github.com/a/b/pull/1")
    assert req.pr_url == "https://github.com/a/b/pull/1"


def test_review_request_accepts_local_repo():
    """提供本地仓库参数应通过校验。"""
    from reviewcrew.schemas import ReviewRequest

    req = ReviewRequest(repo_path="/tmp/repo", base_ref="main", head_ref="feature/x")
    assert req.repo_path == "/tmp/repo"


# ---- Finding ----

def test_finding_requires_confidence_in_range():
    """confidence 必须在 0 到 1 之间。"""
    with pytest.raises(ValidationError):
        make_finding(confidence=1.1)

    with pytest.raises(ValidationError):
        make_finding(confidence=-0.1)


def test_finding_requires_at_least_one_evidence():
    """Finding 至少需要一条代码证据。"""
    from reviewcrew.schemas import Finding

    with pytest.raises(ValidationError):
        make_finding(evidence=[])


def test_finding_producer_must_be_valid():
    """producer 只能是 defect 或 intent。"""
    with pytest.raises(ValidationError):
        make_finding(producer="verifier")


def test_finding_category_must_be_valid():
    """category 必须来自预定义枚举。"""
    with pytest.raises(ValidationError):
        make_finding(category="invalid_category")


def test_finding_severity_must_be_valid():
    """severity 必须来自预定义枚举。"""
    with pytest.raises(ValidationError):
        make_finding(severity="catastrophic")


# ---- PRData ----

def test_pr_data_validates_changed_file_status():
    """ChangedFile.status 必须为预定义枚举值。"""
    from reviewcrew.schemas import PRData, ChangedFile, DiffHunk

    with pytest.raises(ValidationError):
        ChangedFile(
            path="a.py",
            status="moved",  # 无效状态
            additions=1,
            deletions=1,
            hunks=[],
        )


def test_pr_data_accepts_valid_statuses():
    """有效的文件状态应通过校验。"""
    from reviewcrew.schemas import ChangedFile

    for status in ["added", "modified", "deleted", "renamed"]:
        f = ChangedFile(path="x.py", status=status, additions=1, deletions=0, hunks=[])
        assert f.status == status


# ---- Verdict ----

def test_verdict_accepts_confirmed():
    """Verifier 确认的判决应通过校验。"""
    from reviewcrew.schemas import Verdict

    v = Verdict(
        finding_id="f-001",
        accepted=True,
        verdict="confirmed",
        confidence=0.9,
        reason="代码路径可达，无上游校验",
    )
    assert v.accepted is True


def test_verdict_rejects_false_positive():
    """Verifier 拒绝的误报判决应通过校验。"""
    from reviewcrew.schemas import Verdict

    v = Verdict(
        finding_id="f-002",
        accepted=False,
        verdict="false_positive",
        confidence=0.95,
        reason="存在上游输入校验，攻击载荷无法到达",
    )
    assert v.accepted is False


# ---- ReviewResult ----

def test_review_result_must_have_valid_status():
    """ReviewResult.status 只能是 completed/partial/failed。"""
    from reviewcrew.schemas import ReviewResult

    with pytest.raises(ValidationError):
        ReviewResult(
            run_id="r-1",
            status="running",  # 无效状态
            repository="test/repo",
            base_sha="abc",
            head_sha="def",
            findings=[],
            rejected_count=0,
            coverage=[],
            warnings=[],
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            elapsed_seconds=120.0,
        )


# ---- 序列化 ----

def test_pr_data_roundtrip_json():
    """PRData 完整 JSON 序列化往返。"""
    from reviewcrew.schemas import PRData, ChangedFile, DiffHunk

    pr = PRData(
        provider="github",
        repository="acme/demo",
        title="修复登录超时",
        description="增加了会话保持逻辑",
        base_sha="abc123",
        head_sha="def456",
        author="dev",
        files=[
            ChangedFile(
                path="src/login.py",
                status="modified",
                additions=3,
                deletions=2,
                hunks=[
                    DiffHunk(
                        id="h1",
                        file="src/login.py",
                        old_start=10,
                        old_count=5,
                        new_start=10,
                        new_count=6,
                        changed_lines=[12, 13],
                        content="@@ -10,5 +10,6 @@\n context\n+new line\n context",
                    )
                ],
            )
        ],
        raw_diff="diff --git ...",
    )

    json_str = pr.model_dump_json()
    restored = PRData.model_validate_json(json_str)
    assert restored.repository == "acme/demo"
    assert restored.files[0].path == "src/login.py"
    assert restored.files[0].hunks[0].changed_lines == [12, 13]
