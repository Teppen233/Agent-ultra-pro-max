"""审查报告渲染与持久化测试。"""

from datetime import UTC, datetime
import json
from pathlib import Path

from reviewcrew.report import persist_report, render_markdown
from reviewcrew.schemas import CodeEvidence, Finding, ReviewResult


def make_result() -> ReviewResult:
    """构造包含不同严重度的问题，以验证稳定报告输出。"""

    timestamp = datetime(2026, 7, 29, 3, 0, tzinfo=UTC)
    evidence = CodeEvidence(
        source="diff",
        file="src/auth.py",
        start_line=12,
        end_line=14,
        description="新增查询没有限制资源所属用户。",
        content="return repo.get(resource_id)",
    )
    findings = [
        Finding(
            id="low-finding",
            producer="intent",
            category="logic",
            severity="low",
            confidence=0.70,
            file="src/feature.py",
            line_start=20,
            line_end=20,
            title="边界条件遗漏",
            description="空集合会进入错误分支。",
            trigger_condition="调用方传入空集合。",
            impact="请求会失败。",
            reasoning_summary="这是内部推理摘要，不得写入报告。",
            suggestion="为空集合添加提前返回。",
            evidence=[evidence],
            created_at=timestamp,
        ),
        Finding(
            id="high-finding",
            producer="defect",
            category="security",
            severity="high",
            confidence=0.95,
            file="src/auth.py",
            line_start=12,
            line_end=14,
            title="缺少资源归属校验",
            description="接口可读取不属于当前用户的资源。",
            trigger_condition="攻击者提交其他用户的资源标识。",
            impact="攻击者可能读取其他用户的数据。",
            reasoning_summary="模型响应中的思维链绝不能出现。",
            suggestion="读取前验证资源所属用户。",
            evidence=[evidence],
            created_at=timestamp,
        ),
    ]
    return ReviewResult(
        run_id="run-20260729",
        status="partial",
        repository="acme/demo",
        base_sha="base123",
        head_sha="head456",
        findings=findings,
        rejected_count=1,
        coverage=["src/auth.py", "src/feature.py"],
        warnings=["Verifier 超时，已保留已确认的问题。"],
        started_at=timestamp,
        completed_at=timestamp,
        elapsed_seconds=12.5,
    )


def test_render_markdown_contains_required_chinese_sections_in_stable_order() -> None:
    """Markdown 包含问题详情、Verifier 状态、耗时和警告，且按严重度稳定排序。"""

    markdown = render_markdown(make_result())

    for expected in (
        "**严重度**",
        "**类别**",
        "**位置**",
        "**触发条件**",
        "**影响**",
        "**证据**",
        "**建议**",
        "**Verifier 状态**",
        "总耗时：12.50 秒",
        "## 警告",
        "Verifier 超时，已保留已确认的问题。",
    ):
        assert expected in markdown
    assert markdown.index("高危：缺少资源归属校验") < markdown.index("低危：边界条件遗漏")
    assert "src/auth.py:12-14" in markdown
    assert "内部推理摘要" not in markdown
    assert "模型响应" not in markdown


def test_persist_report_creates_utf8_json_and_markdown_without_sensitive_reasoning(
    tmp_path: Path,
) -> None:
    """持久化自动创建目录，JSON 稳定且不保存推理摘要。"""

    json_path, markdown_path = persist_report(make_result(), tmp_path / "runs")

    assert json_path == tmp_path / "runs" / "run-20260729" / "result.json"
    assert markdown_path == tmp_path / "runs" / "run-20260729" / "report.md"
    json_text = json_path.read_text(encoding="utf-8")
    markdown_text = markdown_path.read_text(encoding="utf-8")
    payload = json.loads(json_text)
    assert payload["findings"][0]["id"] == "high-finding"
    assert "reasoning_summary" not in json_text
    assert "思维链" not in json_text
    assert "缺少资源归属校验" in markdown_text
    assert "内部推理摘要" not in markdown_text


def test_persist_report_is_repeatable_for_same_result(tmp_path: Path) -> None:
    """同一结果重复写入时，两个文件内容保持完全一致。"""

    result = make_result()
    first_json, first_markdown = persist_report(result, tmp_path)
    before = (first_json.read_bytes(), first_markdown.read_bytes())
    second_json, second_markdown = persist_report(result, tmp_path)

    assert (second_json.read_bytes(), second_markdown.read_bytes()) == before
