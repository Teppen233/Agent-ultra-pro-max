"""Agent 的协议、预算与受控运行时。"""

from __future__ import annotations

import inspect
from hashlib import sha256
from collections.abc import AsyncIterable, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import ValidationError
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import AgentStreamEvent, FunctionToolCallEvent
from pydantic_ai.models import Model
from pydantic_ai.output import PromptedOutput
from pydantic_ai.usage import RunUsage, UsageLimits

from reviewcrew.config import AgentRole, Config
from reviewcrew.hooks import HookContext, HookManager
from reviewcrew.llm.glm import build_glm_model
from reviewcrew.schemas import AgentSnapshot, Budget, ContextPack, Finding, Verdict

if TYPE_CHECKING:
    from reviewcrew.skills.registry import SkillDefinition


def resolve_role_model(model: Model | None, config: Config, role: AgentRole) -> Model | None:
    """按角色配置解析模型；无密钥时保持离线模式。"""

    if model is not None:
        return model
    if config.llm_api_key is None:
        return None
    role_config = config.model_copy(update={"llm_model": config.model_for(role)})
    return build_glm_model(role_config)


@runtime_checkable
class ReviewAgentProtocol(Protocol):
    """专家 Agent 的标准结构化输出协议。"""

    async def run(
        self,
        context: ContextPack,
        *,
        mailbox: object | None = None,
        blackboard: object | None = None,
    ) -> AgentSnapshot:
        """根据上下文返回可恢复的专家快照。"""


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


@dataclass(frozen=True, slots=True)
class PromptSource:
    """一个可审计的版本化 Prompt 文件来源。"""

    name: str
    path: Path


@dataclass(frozen=True, slots=True)
class RuntimeRecord:
    """不包含 Prompt、响应或密钥的运行审计元数据。"""

    prompt_file_hashes: dict[str, str]
    skills: tuple[tuple[str, str, str], ...]
    output_schema: str
    model_name: str | None


@dataclass(slots=True)
class AgentRuntime:
    """验证 Agent 输出、记录最小事件并限制请求数量。"""

    budget: Budget | None = None
    config: Config = field(default_factory=Config)
    hook_manager: HookManager | None = None
    event_sink: RuntimeEventSink | None = None
    max_validation_retries: int = 1
    _request_count: int = field(default=0, init=False)
    run_records: list[RuntimeRecord] = field(default_factory=list, init=False)

    @property
    def request_count(self) -> int:
        """返回运行时已实际发出的模型请求数。"""

        return self._request_count

    def compose_prompt(
        self,
        *,
        sources: list[PromptSource],
        skills: list[SkillDefinition],
        dynamic_context: str,
        budget: Budget,
        output_schema: str,
        model_name: str | None = None,
    ) -> str:
        """按共享规则、角色、Skill、动态数据、预算和 Schema 的固定顺序组装 Prompt。"""

        source_texts: list[str] = []
        hashes: dict[str, str] = {}
        for source in sources:
            content = source.path.read_text(encoding="utf-8")
            source_texts.append(content)
            hashes[source.name] = sha256(content.encode("utf-8")).hexdigest()
        skill_text = "\n\n".join(skill.content for skill in skills)
        prompt = "\n\n".join(
            [*source_texts, skill_text, dynamic_context, f"剩余预算：{budget.seconds} 秒", f"输出 Schema：{output_schema}"]
        )
        self.run_records.append(
            RuntimeRecord(
                prompt_file_hashes=hashes,
                skills=tuple((skill.name, skill.version, skill.content_hash) for skill in skills),
                output_schema=output_schema,
                model_name=model_name,
            )
        )
        return prompt

    def output_type_for(self, output_type: type[Any]) -> type[Any] | PromptedOutput[Any]:
        """按兼容端点能力选择工具式或提示式结构化输出。"""

        if self.config.llm_output_mode == "prompted":
            return PromptedOutput(output_type)
        return output_type

    async def run_structured(
        self,
        model: Model,
        *,
        role: str,
        sources: list[PromptSource],
        skills: list[SkillDefinition],
        dynamic_context: str,
        budget: Budget,
        output_type: type[Any],
        tools: Sequence[Any] = (),
    ) -> Any:
        """通过统一的 Prompt、预算和重试路径执行结构化模型请求。"""

        prompt = self.compose_prompt(
            sources=sources,
            skills=skills,
            dynamic_context=dynamic_context,
            budget=budget,
            output_schema=output_type.__name__,
            model_name=model.model_name,
        )
        effective_budget = self.budget or budget
        reserved_requests = effective_budget.reserve_requests(self.config.llm_max_retries + 1)
        usage: RunUsage | None = None
        agent_run_started = False
        try:
            usage = RunUsage()
            agent = Agent(
                model,
                output_type=self.output_type_for(output_type),
                retries=self.config.llm_max_retries,
                tools=tools,
            )
            if self.hook_manager is not None:
                await self.hook_manager.run("before_agent", HookContext(role=role))
            agent_run_started = True
            result = await agent.run(
                prompt,
                usage=usage,
                usage_limits=UsageLimits(request_limit=reserved_requests),
                event_stream_handler=self._tool_event_handler(role) if self.event_sink is not None else None,
            )
        except UsageLimitExceeded as error:
            raise RuntimeError("模型请求数已达到预算上限") from error
        finally:
            actual_requests = (
                min(usage.requests, reserved_requests)
                if agent_run_started and usage is not None
                else 0
            )
            effective_budget.release_requests(reserved_requests - actual_requests)
            self._request_count += actual_requests
        if self.hook_manager is not None:
            await self.hook_manager.run("after_agent", HookContext(role=role))
        return result.output

    async def run_expert(
        self,
        agent: ReviewAgentProtocol,
        context: ContextPack,
        *,
        mailbox: object | None = None,
        blackboard: object | None = None,
    ) -> AgentSnapshot:
        """执行专家并校验 AgentSnapshot。"""

        raw_output = await agent.run(context, **self._collaboration_arguments(agent.run, mailbox, blackboard))
        try:
            return raw_output if isinstance(raw_output, AgentSnapshot) else AgentSnapshot.model_validate(raw_output)
        except ValidationError as error:
            raise ValueError("专家输出不符合 AgentSnapshot 结构") from error

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

    def _consume_request(self, budget: Budget | None = None) -> None:
        """统一执行请求预算检查。"""

        effective_budget = self.budget or budget
        if effective_budget is not None:
            effective_budget.consume_request()
        self._request_count += 1

    async def _emit(self, event_name: str, data: dict[str, Any]) -> None:
        """向外部发送不含 Prompt 与原始响应的运行事件。"""

        if self.event_sink is None:
            return
        result = self.event_sink(event_name, data)
        if inspect.isawaitable(result):
            await result

    def _tool_event_handler(self, role: str) -> Callable[[RunContext[Any], AsyncIterable[AgentStreamEvent]], Awaitable[None]]:
        """将真实函数工具调用转换为不含参数的运行时事件。"""

        async def handle(_: RunContext[Any], events: AsyncIterable[AgentStreamEvent]) -> None:
            async for event in events:
                if isinstance(event, FunctionToolCallEvent):
                    await self.record_tool_call(role, event.part.tool_name)

        return handle

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
