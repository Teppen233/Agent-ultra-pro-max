"""验证 HTTP、Orchestrator、SSE、报告、Replay 与前端公开契约的全链路。"""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from reviewcrew.config import Config
from reviewcrew.events import EventStore
from reviewcrew.pipeline.orchestrator import Orchestrator
from reviewcrew.schemas import (
    AgentSnapshot,
    Budget,
    CodeEvidence,
    ContextPack,
    Finding,
    PRData,
    ReviewPlan,
    Verdict,
)
from reviewcrew.server.app import create_app


FRONTEND_EVENT_TYPES = {
    "review.started",
    "review.completed",
    "review.failed",
    "stage.started",
    "stage.completed",
    "stage.failed",
    "agent.started",
    "agent.tool",
    "agent.candidate",
    "agent.completed",
    "agent.failed",
    "plan.published",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "mailbox.message",
    "verifier.started",
    "verifier.accepted",
    "verifier.rejected",
    "verifier.completed",
    "report.generated",
}
PUBLIC_EVENT_FIELDS = {"id", "run_id", "sequence", "timestamp", "type", "data"}
PUBLIC_RESULT_FIELDS = {
    "run_id",
    "status",
    "repository",
    "base_sha",
    "head_sha",
    "findings",
    "rejected_count",
    "coverage",
    "warnings",
    "started_at",
    "completed_at",
    "elapsed_seconds",
}


def _git(repo: Path, *arguments: str) -> str:
    """在临时仓库执行确定性的 Git fixture 命令。"""

    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _make_repository(root: Path) -> tuple[str, str]:
    """创建包含一个可审查权限回归的 base/head。"""

    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "reviewcrew@example.invalid")
    _git(root, "config", "user.name", "ReviewCrew Fixture")
    source = root / "access.py"
    source.write_text(
        "def load_resource(repository, resource_id, user_id):\n"
        "    return repository.get_for_user(resource_id, user_id)\n",
        encoding="utf-8",
    )
    _git(root, "add", "access.py")
    _git(root, "commit", "-m", "base")
    base_sha = _git(root, "rev-parse", "HEAD")

    source.write_text(
        "def load_resource(repository, resource_id, user_id):\n"
        "    return repository.get(resource_id)\n",
        encoding="utf-8",
    )
    _git(root, "add", "access.py")
    _git(root, "commit", "-m", "introduce ownership regression")
    return base_sha, _git(root, "rev-parse", "HEAD")


class _FakeLead:
    """把生产 ContextPack 路由给一个确定性的离线专家。"""

    async def plan(
        self,
        pr: PRData,
        contexts: list[ContextPack],
        budget: Budget,
    ) -> ReviewPlan:
        assert pr.files
        assert contexts and contexts[0].diff_hunks
        return ReviewPlan(
            summary="离线全链路契约验证",
            required_agents=["defect"],
            context_ids=[contexts[0].id],
            shards={"defect": [contexts[0].id]},
            budget_seconds=budget.seconds,
        )


class _FakeExpert:
    """从真实 ContextPack 生成一个结构完整的公开 Finding。"""

    def __init__(self, publisher: object) -> None:
        self.publisher = publisher

    async def run(self, context: ContextPack, **_: object) -> AgentSnapshot:
        hunk = context.diff_hunks[0]
        line = hunk.changed_lines[0]
        finding = Finding(
            id="finding-full-stack",
            producer="defect",
            category="security",
            severity="high",
            confidence=0.94,
            file=hunk.file,
            line_start=line,
            line_end=line,
            title="缺少资源所有权校验",
            description="修改后的查询不再绑定当前用户。",
            trigger_condition="攻击者提交其他用户的资源标识。",
            impact="可能读取其他用户的数据。",
            reasoning_summary="公开结论摘要，不是隐藏推理链。",
            suggestion="恢复按用户限定的资源查询。",
            evidence=[
                CodeEvidence(
                    source="diff",
                    file=hunk.file,
                    start_line=line,
                    end_line=line,
                    description="修改行移除了用户条件。",
                    content="return repository.get(resource_id)",
                )
            ],
            created_at=datetime(2026, 7, 30, tzinfo=UTC),
        )
        await self.publisher.publish(
            sender=f"defect:{context.id}",
            recipient="verifier",
            kind="candidate_finding",
            key=f"candidate:{finding.id}",
            payload={"finding": finding.model_dump(mode="json"), "context_id": context.id},
            correlation_id=finding.id,
        )
        return AgentSnapshot(agent_id=f"defect:{context.id}", findings=[finding])


class _FakeVerifier:
    """消费 Blackboard 中的真实候选消息并给出确定性裁决。"""

    async def watch(
        self,
        mailbox: object,
        blackboard: object,
        budget: Budget,
        *,
        stop_event: asyncio.Event,
        **_: object,
    ) -> list[Verdict]:
        await stop_event.wait()
        messages = blackboard.by_kind("candidate_finding")
        finding = Finding.model_validate(messages[0].payload["finding"])
        return [
            Verdict(
                finding_id=finding.id,
                accepted=True,
                verdict="confirmed",
                confidence=0.96,
                severity="high",
                reason="Fake Verifier 已确认修改行与触发路径。",
                final_finding=finding.model_copy(update={"confidence": 0.96}),
            )
        ]


def _parse_sse(content: str) -> list[dict[str, object]]:
    """解析服务端只使用 data 帧的公开 SSE。"""

    return [
        json.loads(line.removeprefix("data: "))
        for line in content.splitlines()
        if line.startswith("data: ")
    ]


def test_post_fake_orchestrator_sse_result_report_and_replay_match_frontend_contract(
    tmp_path: Path,
) -> None:
    """完整生产边界必须向前端暴露可回放且字段稳定的同一运行。"""

    repo = tmp_path / "fixture-repo"
    base_sha, head_sha = _make_repository(repo)
    runs_dir = tmp_path / "runs"
    config = Config(runs_dir=runs_dir)
    store = EventStore(runs_dir)
    orchestrator = Orchestrator(
        config,
        event_store=store,
        team_lead=_FakeLead(),
        defect_factory=lambda publisher: _FakeExpert(publisher),
        verifier_factory=lambda _publisher: _FakeVerifier(),
        budget_grace_seconds=0,
    )
    app = create_app(config=config, event_store=store, orchestrator=orchestrator)

    with TestClient(app) as client:
        started = client.post(
            "/api/reviews",
            json={
                "repo_path": str(repo),
                "base_ref": base_sha,
                "head_ref": head_sha,
            },
        )
        assert started.status_code == 202
        assert started.json()["status"] == "running"
        run_id = started.json()["run_id"]

        live = client.get(f"/api/reviews/{run_id}/events")
        result = client.get(f"/api/reviews/{run_id}")
        json_report = client.get(f"/api/reviews/{run_id}/report?format=json")
        markdown_report = client.get(f"/api/reviews/{run_id}/report?format=markdown")
        replay = client.get(f"/api/replays/{run_id}/events?speed=8")

    live_events = _parse_sse(live.text)
    replay_events = _parse_sse(replay.text)
    result_payload = result.json()

    assert live.status_code == replay.status_code == 200
    assert live.headers["content-type"].startswith("text/event-stream")
    assert [event["sequence"] for event in live_events] == list(range(1, len(live_events) + 1))
    assert replay_events == live_events
    assert all(set(event) == PUBLIC_EVENT_FIELDS for event in live_events)
    assert all(event["run_id"] == run_id for event in live_events)
    assert {str(event["type"]) for event in live_events} <= FRONTEND_EVENT_TYPES
    assert live_events[0]["type"] == "review.started"
    assert live_events[0]["data"] == {
        "mode": "local",
        "repository": repo.name,
        "title": f"本地审查 {base_sha} → {head_sha}",
    }
    assert live_events[-1]["type"] == "review.completed"
    assert live_events[-1]["data"] == {"status": "completed"}
    plan = next(event for event in live_events if event["type"] == "plan.published")
    assert plan["data"]["summary"] == "离线全链路契约验证"
    assert plan["data"]["context_ids"]
    tool_names = {
        event["data"]["tool_name"]
        for event in live_events
        if str(event["type"]).startswith("tool.")
    }
    assert {
        "git.load_diff",
        "diff.parse",
        "context.read_docs",
        "context.read_file",
        "context.find_tests",
        "static.semgrep",
        "report.persist",
    } <= tool_names
    mailbox = next(event for event in live_events if event["type"] == "mailbox.message")
    assert mailbox["data"]["kind"] == "candidate_finding"
    assert "tool_name" not in mailbox["data"]
    serialized_events = json.dumps(live_events, ensure_ascii=False).casefold()
    for forbidden in ("prompt", "reasoning", "api_key", "raw_response"):
        assert forbidden not in serialized_events
    candidate = next(event for event in live_events if event["type"] == "agent.candidate")
    assert str(candidate["data"]["agent"]).startswith("defect:ctx-")
    assert {key: value for key, value in candidate["data"].items() if key != "agent"} == {
        "finding_id": "finding-full-stack",
        "file": "access.py",
        "line": 2,
        "severity": "high",
    }
    accepted = next(event for event in live_events if event["type"] == "verifier.accepted")
    assert accepted["data"] == {
        "finding_id": "finding-full-stack",
        "verdict": "confirmed",
        "confidence": 0.96,
    }

    assert result.status_code == json_report.status_code == markdown_report.status_code == 200
    assert result_payload == json_report.json()
    assert set(result_payload) == PUBLIC_RESULT_FIELDS
    assert result_payload["status"] == "completed"
    assert result_payload["repository"] == repo.name
    assert result_payload["base_sha"] == base_sha
    assert result_payload["head_sha"] == head_sha
    assert result_payload["coverage"] == ["access.py"]
    assert [finding["id"] for finding in result_payload["findings"]] == ["finding-full-stack"]
    assert set(result_payload["findings"][0]) == {
        "id",
        "producer",
        "category",
        "severity",
        "confidence",
        "file",
        "line_start",
        "line_end",
        "title",
        "description",
        "trigger_condition",
        "impact",
        "suggestion",
        "evidence",
        "created_at",
    }
    assert "reasoning_summary" not in result_payload["findings"][0]
    assert "# ReviewCrew 审查报告" in markdown_report.text
    assert "缺少资源所有权校验" in markdown_report.text

    run_dir = runs_dir / run_id
    assert {"events.jsonl", "result.json", "report.md"} <= {
        path.name for path in run_dir.iterdir() if path.is_file()
    }
    persisted_events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    persisted_result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    persisted_markdown = (run_dir / "report.md").read_text(encoding="utf-8")
    assert persisted_events == live_events
    assert persisted_result == result_payload
    assert persisted_markdown == markdown_report.text
