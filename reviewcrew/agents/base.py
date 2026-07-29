"""Agent 的协议、预算与受控运行时。"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from pydantic import ValidationError

from reviewcrew.schemas import Budget, ContextPack, Finding, Verdict


@runtime_checkable
class ReviewAgentProtocol(Protocol):
    """专家 Agent 的标准结构化输出协议。"""

    async def run(
        self,
        context: ContextPack,
        *,
        mailbox: object | None = None,
        blackboard: object | None = None,
    ) -> list[Finding]:
        """根据上下文返回候选问题。"""


@runtime_checkable
class VerifierProtocol(Protocol):
    """Verifier Agent 的标准结构化输出协议。"""

    async def run(
        self,
        findings: list[Finding],
        context: list[ContextPack],
        *,
        mailbox: object | None = None,
        blackboard: object | None = None,
    ) -> list[Verdict]:
        """校验候选问题并返回裁决。"""


RuntimeEventSink = Callable[[str, dict[str, Any]], Awaitable[None] | None]


@dataclass(slots=True)
class AgentRuntime:
    """验证 Agent 输出、记录最小事件并限制请求数量。"""

    budget: Budget | None = None
    event_sink: RuntimeEventSink | None = None
    max_validation_retries: int = 1
    _request_count: int = field(default=0, init=False)

    async def run_expert(
        self,
        agent: ReviewAgentProtocol,
        context: ContextPack,
        *,
        mailbox: object | None = None,
        blackboard: object | None = None,
    ) -> list[Finding]:
        """执行专家并校验 Finding 列表。"""

        output = await self._run_with_validation(
            agent.run,
            (context,),
            self._collaboration_arguments(agent.run, mailbox, blackboard),
            Finding,
            "专家",
        )
        return output

    async def run_verifier(
        self,
        agent: VerifierProtocol,
        findings: list[Finding],
        context: list[ContextPack],
        *,
        mailbox: object | None = None,
        blackboard: object | None = None,
    ) -> list[Verdict]:
        """执行校验器并校验 Verdict 列表。"""

        output = await self._run_with_validation(
            agent.run,
            (findings, context),
            self._collaboration_arguments(agent.run, mailbox, blackboard),
            Verdict,
            "校验器",
        )
        return output

    async def record_tool_call(self, role: str, tool_name: str) -> None:
        """记录不含参数和内容的工具调用事件。"""

        await self._emit("agent.tool", {"role": role, "tool_name": tool_name})

    async def _run_with_validation(
        self,
        callable_agent: Callable[..., Awaitable[list[Any]]],
        arguments: tuple[Any, ...],
        keyword_arguments: dict[str, object],
        output_type: type[Finding] | type[Verdict],
        agent_label: str,
    ) -> list[Any]:
        attempts = 0
        while True:
            self._consume_request()
            raw_output = await callable_agent(*arguments, **keyword_arguments)
            try:
                if not isinstance(raw_output, list):
                    raise ValueError(f"{agent_label}输出必须是列表")
                return [item if isinstance(item, output_type) else output_type.model_validate(item) for item in raw_output]
            except (ValidationError, TypeError, ValueError) as error:
                if attempts >= self.max_validation_retries:
                    raise ValueError(f"{agent_label}输出不符合{output_type.__name__}结构") from error
                attempts += 1

    def _consume_request(self) -> None:
        """统一执行请求预算检查。"""

        if self.budget is not None:
            self.budget.consume_request()
        self._request_count += 1

    async def _emit(self, event_name: str, data: dict[str, Any]) -> None:
        """向外部发送不含 Prompt 与原始响应的运行事件。"""

        if self.event_sink is None:
            return
        result = self.event_sink(event_name, data)
        if inspect.isawaitable(result):
            await result

    @staticmethod
    def _collaboration_arguments(
        handler: Callable[..., Awaitable[list[Any]]],
        mailbox: object | None,
        blackboard: object | None,
    ) -> dict[str, object]:
        """仅向声明协作参数的后续 Agent 传递共享对象。"""

        parameters = inspect.signature(handler).parameters
        accepts_keywords = any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
        arguments: dict[str, object] = {}
        if accepts_keywords or "mailbox" in parameters:
            arguments["mailbox"] = mailbox
        if accepts_keywords or "blackboard" in parameters:
            arguments["blackboard"] = blackboard
        return arguments
