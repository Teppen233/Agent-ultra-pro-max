"""运行时 Hook 的注册、执行与安全拒绝机制。"""

from __future__ import annotations

import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal


logger = logging.getLogger(__name__)
HookName = Literal["before_agent", "after_agent", "before_tool", "after_tool"]


class HookRejectedError(PermissionError):
    """表示安全 Hook 已明确拒绝本次操作。"""


@dataclass(frozen=True, slots=True)
class HookContext:
    """传递给 Hook 的最小元信息，不包含完整 Prompt 或原始响应。"""

    role: str
    tool_name: str | None = None
    tool_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


HookHandler = Callable[[HookContext], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class _RegisteredHook:
    handler: HookHandler
    security: bool


class HookManager:
    """顺序运行 Hook；普通异常降级，安全拒绝必须传播。"""

    def __init__(self) -> None:
        self._hooks: dict[str, list[_RegisteredHook]] = defaultdict(list)

    def register(self, name: HookName, handler: HookHandler, *, security: bool = False) -> None:
        """注册一个 Hook，安全 Hook 可拒绝操作。"""

        self._hooks[name].append(_RegisteredHook(handler=handler, security=security))

    async def run(self, name: HookName, context: HookContext) -> None:
        """运行指定 Hook，不让普通 Hook 异常阻断主管道。"""

        for registered in self._hooks.get(name, []):
            try:
                result = registered.handler(context)
                if inspect.isawaitable(result):
                    await result
            except HookRejectedError:
                if registered.security:
                    raise
                logger.warning("普通 Hook 请求拒绝，已忽略：%s", name)
            except Exception as error:
                logger.warning("Hook 执行异常，已忽略：%s（%s）", name, type(error).__name__)
