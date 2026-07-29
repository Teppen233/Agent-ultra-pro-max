"""管理 Agent 工具权限、预算和调用约束。"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """一个受限工具的注册信息。"""

    name: str
    description: str
    roles: frozenset[str]
    timeout_seconds: float
    max_output_characters: int
    handler: Callable[..., Any]


class ToolRegistry:
    """按角色授权并统一调用工具。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        """注册工具，重复名称会被拒绝。"""

        if definition.name in self._tools:
            raise ValueError(f"工具已经注册：{definition.name}")
        self._tools[definition.name] = definition

    async def invoke(self, role: str, name: str, arguments: dict[str, Any]) -> Any:
        """校验角色后调用同步或异步工具。"""

        definition = self._tools.get(name)
        if definition is None:
            raise KeyError(f"工具不存在：{name}")
        if role not in definition.roles:
            raise PermissionError(f"角色 {role} 无权调用工具 {name}")
        result = definition.handler(**arguments)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, str) and len(result) > definition.max_output_characters:
            return result[: definition.max_output_characters]
        return result

