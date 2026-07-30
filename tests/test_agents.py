from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic_ai.agent import Agent
from pydantic_ai import RunContext
from pydantic_ai import UnexpectedModelBehavior
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import UsageLimits

from reviewcrew.agents.base import (
    AgentDeps,
    AgentFindings,
    AgentRuntime,
    ReviewAgent,
    prepare_checkpoint_tools,
    submit_snapshot,
)
from reviewcrew.events import EventLogger
from reviewcrew.models import ContextPack, Finding, PipelineEvent
from reviewcrew.profile.indexer import RepoIndex
from reviewcrew.tools.toolbox import Toolbox


def _finding() -> Finding:
    return Finding(
        category="security",
        severity="high",
        confidence=0.9,
        file="app.py",
        line_start=1,
        line_end=1,
        title="测试候选问题",
        reasoning="存在可达风险。",
        trigger_path="入口 -> 风险点",
        suggestion="限制访问范围。",
    )


async def test_timeout_recovers_latest_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class SlowRunner:
        async def run(
            self, prompt: str, *, deps: AgentDeps, usage_limits: UsageLimits
        ) -> None:
            del prompt
            assert usage_limits.request_limit is None
            assert usage_limits.tool_calls_limit is None
            assert usage_limits.total_tokens_limit is None
            deps.snapshots.extend([[], [_finding()]])
            await asyncio.sleep(1)

    agent = ReviewAgent("defect", "test")
    monkeypatch.setattr(
        agent,
        "_build_agent",
        lambda: cast("Agent[AgentDeps, AgentFindings]", SlowRunner()),
    )
    root = tmp_path / "repo"
    root.mkdir()

    findings = await agent.run(
        ContextPack(pack_id="pack", diff_hunks=[]),
        Toolbox(root, RepoIndex.build(root, ["python"])),
        AgentRuntime(timeout_seconds=0.01),
    )

    assert findings == [_finding()]


async def test_checkpoint_forces_snapshot_and_preserves_previous_findings(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    logger = EventLogger("checkpoint", tmp_path / "runs")
    captured: list[PipelineEvent] = []
    logger.subscribe(captured.append)
    deps = AgentDeps(
        toolbox=Toolbox(root, RepoIndex.build(root, ["python"])),
        event_logger=logger,
        role="defect",
        task_id="task-1",
        checkpoint_interval=2,
    )
    deps.record_tool("read_file", {"path": "one.py"})
    deps.record_tool("read_file", {"path": "two.py"})
    ctx = cast("RunContext[AgentDeps]", SimpleNamespace(deps=deps))
    tools = [ToolDefinition(name="read_file"), ToolDefinition(name="submit_snapshot")]

    assert [tool.name for tool in prepare_checkpoint_tools(ctx, tools)] == [
        "submit_snapshot"
    ]

    finding = _finding()
    assert finding.id
    await submit_snapshot(ctx, [finding])
    assert deps.checkpoint_required is False
    assert deps.tool_calls_since_snapshot == 0
    assert prepare_checkpoint_tools(ctx, tools) == tools

    await submit_snapshot(ctx, [])
    assert deps.snapshots[-1] == [finding]
    snapshots = [event for event in captured if event.type == "snapshot"]
    assert snapshots[-1].snapshot_findings == [finding]


async def test_unexpected_model_behavior_recovers_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    finding = _finding()

    class BrokenRunner:
        async def run(
            self, prompt: str, *, deps: AgentDeps, usage_limits: UsageLimits
        ) -> None:
            nonlocal calls
            del prompt, usage_limits
            calls += 1
            deps.snapshots.append([finding])
            raise UnexpectedModelBehavior("invalid structured response")

    async def no_sleep(_: float) -> None:
        return None

    agent = ReviewAgent("defect", "test")
    monkeypatch.setattr(
        agent,
        "_build_agent",
        lambda: cast("Agent[AgentDeps, AgentFindings]", BrokenRunner()),
    )
    monkeypatch.setattr("reviewcrew.llm.glm.asyncio.sleep", no_sleep)
    root = tmp_path / "repo"
    root.mkdir()

    findings = await agent.run(
        ContextPack(pack_id="pack", diff_hunks=[]),
        Toolbox(root, RepoIndex.build(root, ["python"])),
        AgentRuntime(timeout_seconds=1),
    )

    assert calls == 4
    assert findings == [finding]
