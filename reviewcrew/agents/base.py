from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext, UnexpectedModelBehavior
from pydantic_ai.capabilities import PrepareTools
from pydantic_ai.models import Model
from pydantic_ai.tools import ToolDefinition

from reviewcrew.events import EventLogger
from reviewcrew.llm.glm import (
    build_glm_model,
    build_model_settings,
    retry_unexpected_model_behavior,
    unlimited_usage,
)
from reviewcrew.models import AgentName, ContextPack, Finding, PipelineEvent
from reviewcrew.tools.toolbox import Toolbox


class AgentFindings(BaseModel):
    findings: list[Finding]


class AgentRuntime(BaseModel):
    timeout_seconds: float = Field(gt=0)
    checkpoint_interval: int = Field(default=10, ge=1)


@dataclass
class AgentDeps:
    toolbox: Toolbox
    event_logger: EventLogger | None
    role: AgentName
    task_id: str | None = None
    snapshots: list[list[Finding]] = field(default_factory=list)
    checkpoint_interval: int = 10
    tool_calls_since_snapshot: int = 0
    total_tool_calls: int = 0
    checkpoint_required: bool = False

    def emit(self, event_type: str, **values: Any) -> None:
        if self.event_logger is None:
            return
        self.event_logger.emit(
            PipelineEvent(
                timestamp=time.time(),
                type=event_type,
                agent=self.role,
                task_id=self.task_id,
                **values,
            )
        )

    def record_tool(self, tool: str, args: dict[str, object]) -> None:
        self.total_tool_calls += 1
        self.tool_calls_since_snapshot += 1
        self.emit("tool", tool=tool, args=args)
        if self.tool_calls_since_snapshot >= self.checkpoint_interval:
            self.checkpoint_required = True


def prepare_checkpoint_tools(
    ctx: RunContext[AgentDeps], tool_defs: list[ToolDefinition]
) -> list[ToolDefinition]:
    if not ctx.deps.checkpoint_required:
        return tool_defs
    return [tool for tool in tool_defs if tool.name == "submit_snapshot"]


async def read_file(
    ctx: RunContext[AgentDeps], path: str, start: int | None = None, end: int | None = None
) -> str:
    ctx.deps.record_tool("read_file", {"path": path, "start": start, "end": end})
    try:
        return await ctx.deps.toolbox.read_file(path, start, end)
    except (OSError, ValueError) as error:
        return f"工具调用失败：{type(error).__name__}: {error}"


async def find_references(
    ctx: RunContext[AgentDeps], symbol: str
) -> list[dict[str, object]] | str:
    ctx.deps.record_tool("find_references", {"symbol": symbol})
    try:
        return await ctx.deps.toolbox.find_references(symbol)
    except (OSError, ValueError) as error:
        return f"工具调用失败：{type(error).__name__}: {error}"


async def get_callers(
    ctx: RunContext[AgentDeps], function: str
) -> list[dict[str, object]] | str:
    ctx.deps.record_tool("get_callers", {"function": function})
    try:
        return await ctx.deps.toolbox.get_callers(function)
    except (OSError, ValueError) as error:
        return f"工具调用失败：{type(error).__name__}: {error}"


async def get_callees(
    ctx: RunContext[AgentDeps], function: str
) -> list[dict[str, object]] | str:
    ctx.deps.record_tool("get_callees", {"function": function})
    try:
        return await ctx.deps.toolbox.get_callees(function)
    except (OSError, ValueError) as error:
        return f"工具调用失败：{type(error).__name__}: {error}"


async def git_blame(ctx: RunContext[AgentDeps], path: str, start: int, end: int) -> str:
    ctx.deps.record_tool("git_blame", {"path": path, "start": start, "end": end})
    try:
        return await ctx.deps.toolbox.git_blame(path, start, end)
    except (OSError, ValueError) as error:
        return f"工具调用失败：{type(error).__name__}: {error}"


async def run_semgrep_rule(ctx: RunContext[AgentDeps], rule_id: str, path: str) -> str:
    ctx.deps.record_tool("run_semgrep_rule", {"rule_id": rule_id, "path": path})
    try:
        return await ctx.deps.toolbox.run_semgrep_rule(rule_id, path)
    except (OSError, ValueError) as error:
        return f"工具调用失败：{type(error).__name__}: {error}"


async def submit_snapshot(ctx: RunContext[AgentDeps], findings: list[Finding]) -> str:
    previous = ctx.deps.snapshots[-1] if ctx.deps.snapshots else []
    merged = {finding.id: finding for finding in previous}
    merged.update({finding.id: finding for finding in findings})
    snapshot = list(merged.values())
    ctx.deps.snapshots.append(snapshot)
    checkpoint_calls = ctx.deps.tool_calls_since_snapshot
    ctx.deps.tool_calls_since_snapshot = 0
    ctx.deps.checkpoint_required = False
    ctx.deps.emit(
        "tool",
        tool="submit_snapshot",
        args={
            "count": len(snapshot),
            "submitted": len(findings),
            "tool_calls": checkpoint_calls,
        },
    )
    ctx.deps.emit(
        "snapshot",
        text=f"阶段性保存 {len(snapshot)} 条候选 Finding。",
        snapshot_findings=snapshot,
    )
    return f"已累计保存 {len(snapshot)} 条候选 Finding，可以继续取证。"


class ReviewAgent:
    def __init__(
        self,
        role: AgentName,
        system_prompt: str,
        model: Model | None = None,
        event_logger: EventLogger | None = None,
    ) -> None:
        self.role = role
        self.system_prompt = system_prompt
        self.model = model
        self.event_logger = event_logger

    def _build_agent(self) -> Agent[AgentDeps, AgentFindings]:
        return Agent(
            self.model or build_glm_model(),
            output_type=AgentFindings,
            deps_type=AgentDeps,
            system_prompt=self.system_prompt,
            model_settings=build_model_settings(0.2),
            retries=3,
            capabilities=[PrepareTools(prepare_checkpoint_tools)],
            tools=[
                read_file,
                find_references,
                get_callers,
                get_callees,
                git_blame,
                run_semgrep_rule,
                submit_snapshot,
            ],
        )

    async def run(
        self,
        pack: ContextPack,
        toolbox: Toolbox,
        runtime: AgentRuntime,
        task_id: str | None = None,
        objective: str | None = None,
    ) -> list[Finding]:
        deps = AgentDeps(
            toolbox=toolbox,
            event_logger=self.event_logger,
            role=self.role,
            task_id=task_id,
            checkpoint_interval=runtime.checkpoint_interval,
        )
        deps.emit("agent", agent_status="running")
        deps.emit("thought", text=f"开始执行任务：{objective or pack.pack_id}")
        prompt = pack.model_dump_json(indent=2)
        if objective:
            prompt = f"本次审查任务：{objective}\n\n{prompt}"

        def merge_findings(items: list[Finding]) -> list[Finding]:
            merged = {
                finding.id: finding
                for finding in (deps.snapshots[-1] if deps.snapshots else [])
            }
            merged.update({finding.id: finding for finding in items})
            return list(merged.values())

        def emit_retry(
            retry_number: int, max_retries: int, error: UnexpectedModelBehavior
        ) -> None:
            detail = str(error).replace("\n", " ")[:500]
            deps.emit(
                "thought",
                text=(
                    f"模型响应异常，正在进行第 {retry_number}/{max_retries} 次自动重试："
                    f"{detail}"
                ),
            )

        async def invoke() -> AgentFindings:
            retry_prompt = prompt
            if deps.snapshots:
                retry_prompt += (
                    "\n\n已有阶段性候选，请在继续调查时保留并复核：\n"
                    + "\n".join(
                        finding.model_dump_json() for finding in deps.snapshots[-1]
                    )
                )
            result = await self._build_agent().run(
                retry_prompt,
                deps=deps,
                usage_limits=unlimited_usage(),
            )
            return result.output

        try:
            async with asyncio.timeout(runtime.timeout_seconds):
                output = await retry_unexpected_model_behavior(
                    invoke,
                    on_retry=emit_retry,
                )
                findings = merge_findings(output.findings)
        except UnexpectedModelBehavior as error:
            if not deps.snapshots:
                raise
            findings = deps.snapshots[-1]
            deps.emit(
                "thought",
                text=(
                    "模型响应连续异常，已恢复最近阶段性结果 "
                    f"({len(findings)} 条)：{str(error).replace(chr(10), ' ')[:500]}"
                ),
            )
        except (TimeoutError, ExceptionGroup):
            findings = deps.snapshots[-1] if deps.snapshots else []
            deps.emit(
                "thought",
                text=f"任务达到时间边界，恢复最近一次阶段性结果 ({len(findings)} 条)。",
            )
        deps.emit("agent", agent_status="done")
        return findings
