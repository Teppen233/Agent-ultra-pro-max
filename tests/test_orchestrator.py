"""Orchestrator 与报告测试 —— Fake 模式下的端到端编排验证。"""

import pytest
from pathlib import Path


@pytest.mark.asyncio
async def test_orchestrator_fake_end_to_end(tmp_path: Path, monkeypatch):
    """Fake 模式下 Orchestrator 应完成完整编排并产出结果。"""
    from reviewcrew.config import Config
    from reviewcrew.events import EventStore
    from reviewcrew.pipeline.orchestrator import Orchestrator
    from reviewcrew.schemas import ReviewRequest

    config = Config.from_env()
    config.runs_dir = str(tmp_path / "runs")

    store = EventStore(config.runs_dir)
    orch = Orchestrator(config, store)

    # 使用 Fake 模型
    from reviewcrew.llm.glm import build_fake_model
    orch.model = build_fake_model()

    # 使用本地模式避免真实 HTTP 调用
    import subprocess
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@test.com",
    }
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
    (repo_dir / "main.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, capture_output=True, env=env)

    result = await orch.review(
        ReviewRequest(
            repo_path=str(repo_dir),
            base_ref="HEAD",
            head_ref="HEAD",
        )
    )

    assert result is not None
    assert result.status in ("completed", "partial")


@pytest.mark.asyncio
async def test_orchestrator_records_warnings_on_failure(tmp_path: Path):
    """Agent 失败时应记录中文警告。"""
    from reviewcrew.config import Config
    from reviewcrew.events import EventStore
    from reviewcrew.pipeline.orchestrator import Orchestrator
    from reviewcrew.schemas import ReviewRequest

    config = Config.from_env()
    config.runs_dir = str(tmp_path / "runs")
    config.pr_load_timeout_seconds = 1  # 极短超时

    store = EventStore(config.runs_dir)
    orch = Orchestrator(config, store)

    result = await orch.review(
        ReviewRequest(
            repo_path="/nonexistent/path",
            base_ref="main",
            head_ref="feature/x",
        )
    )

    assert result.status in ("partial", "failed")
    assert len(result.warnings) >= 1


def test_report_markdown_contains_required_sections():
    """Markdown 报告应包含严重度、类别、行号、影响和建议。"""
    from reviewcrew.pipeline.report import render_markdown
    from reviewcrew.schemas import ReviewResult, Finding, CodeEvidence
    from datetime import datetime, timezone

    result = ReviewResult(
        run_id="run-1",
        status="completed",
        repository="test/repo",
        base_sha="abc",
        head_sha="def",
        findings=[
            Finding(
                id="f-001",
                producer="defect",
                category="security",
                severity="high",
                confidence=0.9,
                file="src/login.py",
                line_start=42,
                line_end=45,
                title="SQL 注入风险",
                description="用户输入未过滤",
                trigger_condition="传入单引号",
                impact="数据泄漏",
                reasoning_summary="直接拼接 SQL",
                suggestion="使用参数化查询",
                evidence=[
                    CodeEvidence(
                        file="src/login.py",
                        line_start=42,
                        line_end=45,
                        content="query = f\"SELECT...\"",
                        language="python",
                    )
                ],
            )
        ],
        rejected_count=2,
        coverage=["security", "logic"],
        warnings=[],
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        elapsed_seconds=120.0,
    )

    md = render_markdown(result)
    assert "SQL 注入" in md
    assert "src/login.py" in md
    assert "参数化查询" in md
    assert "安全漏洞" in md  # category label
