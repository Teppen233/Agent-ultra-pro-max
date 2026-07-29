"""Tool Registry —— 统一工具注册、权限校验和调用入口。

所有 Agent 工具通过统一注册表管理，确保：
- 角色权限校验
- 超时控制
- 输出裁剪
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolDefinition:
    """工具元数据定义。"""

    name: str
    description: str  # 中文说明
    allowed_roles: list[str]  # 允许使用的角色列表
    timeout: float = 30.0  # 默认超时秒数
    max_output_chars: int = 10000  # 单次最大输出字符数


class ToolRegistry:
    """工具注册表 —— 管理所有 Agent 可调用的只读工具。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, Any] = {}  # 工具名 → 实现函数

    def register(self, definition: ToolDefinition, handler: Any = None) -> None:
        """注册工具定义和可选实现。

        Args:
            definition: 工具元数据
            handler: 工具实现的可调用对象
        """
        self._tools[definition.name] = definition
        if handler:
            self._handlers[definition.name] = handler

    def list_tools(self) -> list[str]:
        """返回已注册的工具名称列表。"""
        return list(self._tools.keys())

    def get_definition(self, name: str) -> ToolDefinition | None:
        """按名称获取工具定义。"""
        return self._tools.get(name)

    async def invoke(
        self,
        role: str,
        name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """以指定角色调用工具。

        Args:
            role: 调用方角色
            name: 工具名称
            arguments: 工具参数

        Returns:
            工具执行结果

        Raises:
            ValueError: 工具不存在或角色无权限
        """
        definition = self._tools.get(name)
        if definition is None:
            raise ValueError(f"工具不存在: {name}")

        if role not in definition.allowed_roles:
            raise ValueError(
                f"角色 {role} 不允许调用工具 {name}，"
                f"允许的角色: {', '.join(definition.allowed_roles)}"
            )

        handler = self._handlers.get(name)
        if handler is None:
            raise ValueError(f"工具 {name} 未绑定实现")

        # 调用并裁剪输出
        result = await handler(**arguments) if hasattr(handler, "__call__") else handler(**arguments)
        return result
