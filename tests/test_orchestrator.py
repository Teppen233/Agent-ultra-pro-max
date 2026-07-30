from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from reviewcrew.agents.base import AgentRuntime
from reviewcrew.agents.coordinator import ReviewPlan, fallback_plan
from reviewcrew.models import ContextPack, Finding, Severity, Verdict
from reviewcrew.pipeline.context import PRMeta
from reviewcrew.pipeline.orchestrator import Orchestrator
from reviewcrew.tools.toolbox import Toolbox

DIFF = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-value = 1
+value = user_input
"""


class FakeExpert:
    def __init__(self, title: str, severity: Severity = "high") -> None:
        self.title = title
        self.severity = severity

    async def run(
        self,
        pack: ContextPack,
        toolbox: Toolbox,
        runtime: AgentRuntime,
        task_id: str | None = None,
        objective: str | None = None,
    ) -> list[Finding]:
        del pack, toolbox, runtime, task_id, objective
        return [
            Finding(
                category="logic",
                severity=self.severity,
                confidence=0.8,
                file="app.py",
                line_start=1,
                line_end=1,
                title=self.title,
                reasoning="Changed input is not validated.",
                trigger_path="request -> assignment",
                suggestion="Validate the input.",
            )
        ]


class FakeVerifier:
    async def run(
        self,
        findings: list[Finding],
        toolbox: Toolbox,
        timeout_seconds: float = 120,
        task_id: str | None = None,
    ) -> list[Verdict]:
        del toolbox, timeout_seconds, task_id
        return [
            Verdict(
                finding_id=finding.id,
                verdict="keep",
                reason="reachable",
                confidence_adjusted=0.9,
            )
            for finding in findings
        ]


class FakeCoordinator:
    async def run(
        self, packs: list[ContextPack], timeout_seconds: float = 45
    ) -> ReviewPlan:
        del timeout_seconds
        return fallback_plan(packs, "测试调度计划")


async def test_orchestrator_emits_dynamic_workflow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("value = user_input\n", encoding="utf-8")

    async def diff_loader(_: str) -> str:
        return DIFF

    async def meta_loader(_: str) -> PRMeta:
        return PRMeta(title="Validate input")

    orchestrator = Orchestrator(
        runs_dir=tmp_path / "runs",
        diff_loader=diff_loader,
        meta_loader=meta_loader,
        signal_providers=[],
        defect_agent=FakeExpert("Missing validation"),
        intent_agent=FakeExpert("Intent mismatch"),
        verifier=FakeVerifier(),
        coordinator=FakeCoordinator(),
    )
    result = await orchestrator.review("test", repo)
    events_path = tmp_path / "runs" / result.run_id / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    stage_events = [event for event in events if event["type"] == "stage"]
    assert stage_events == []
    assert set(result.stages) == {
        "preprocess",
        "context",
        "coordinate",
        "schedule",
        "report",
    }
    nodes = [event["workflow_node"] for event in events if event["type"] == "workflow_node"]
    edges = [event["workflow_edge"] for event in events if event["type"] == "workflow_edge"]
    assert {node["kind"] for node in nodes} >= {
        "input",
        "coordinator",
        "agent_task",
        "finding",
        "verifier",
        "report",
    }
    assert {edge["relation"] for edge in edges} >= {
        "dispatch",
        "handoff",
        "candidate",
        "challenge",
        "result",
    }
    assert len(result.findings) == 1
    report_event = next(event for event in events if event["type"] == "report")
    assert report_event["findings"] == [
        finding.model_dump(exclude_none=True) for finding in result.findings
    ]
    assert (events_path.parent / "report.md").exists()


async def test_experts_run_in_parallel(tmp_path: Path) -> None:
    class SlowExpert(FakeExpert):
        async def run(
            self,
            pack: ContextPack,
            toolbox: Toolbox,
            runtime: AgentRuntime,
            task_id: str | None = None,
            objective: str | None = None,
        ) -> list[Finding]:
            import asyncio

            await asyncio.sleep(0.1)
            return await super().run(pack, toolbox, runtime, task_id, objective)

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("value = user_input\n", encoding="utf-8")

    async def diff_loader(_: str) -> str:
        return DIFF

    started = time.monotonic()
    orchestrator = Orchestrator(
        runs_dir=tmp_path / "runs",
        diff_loader=diff_loader,
        signal_providers=[],
        defect_agent=SlowExpert("one", "medium"),
        intent_agent=SlowExpert("two", "medium"),
        verifier=FakeVerifier(),
        coordinator=FakeCoordinator(),
    )
    await orchestrator.review("test", repo)
    assert time.monotonic() - started < 0.18


async def test_global_watchdog_cancels_pipeline(tmp_path: Path) -> None:
    import asyncio

    repo = tmp_path / "repo"
    repo.mkdir()

    async def slow_diff_loader(_: str) -> str:
        await asyncio.sleep(0.05)
        return DIFF

    orchestrator = Orchestrator(
        runs_dir=tmp_path / "runs",
        diff_loader=slow_diff_loader,
        signal_providers=[],
        pipeline_timeout_seconds=0.01,
    )

    with pytest.raises(TimeoutError):
        await orchestrator.review("test", repo)
