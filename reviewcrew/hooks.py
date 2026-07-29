"""生命周期 Hooks —— 确定性的审查生命周期事件回调。

Hook 只能记录、校验和裁剪，不得修改模型结论本身。
安全校验 Hook 失败必须拒绝相应操作，其他 Hook 失败只能记录告警。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Hook 名称枚举
HookName = str

# Hook 回调签名
HookCallback = Callable[["HookContext"], None]


class HookContext:
    """Hook 上下文 —— 携带当前阶段、Agent 和运行信息。"""

    def __init__(self, **kwargs: Any) -> None:
        self.data: dict[str, Any] = kwargs

    def __getattr__(self, name: str) -> Any:
        if name in self.data:
            return self.data[name]
        raise AttributeError(f"HookContext 没有属性: {name}")


class HookManager:
    """Hook 管理器 —— 注册和触发生命周期回调。"""

    def __init__(self) -> None:
        self._hooks: dict[HookName, list[HookCallback]] = {}

    def register(self, name: HookName, callback: HookCallback) -> None:
        """注册一个 Hook 回调。

        Args:
            name: Hook 名称，如 before_run, after_agent
            callback: 回调函数，接收 HookContext
        """
        self._hooks.setdefault(name, []).append(callback)

    def run(self, name: HookName, context: HookContext | None = None) -> None:
        """触发指定名称的所有 Hook。

        Hook 异常只记录告警，不阻塞主管道。
        安全校验 Hook（以 before_ 开头且名称含 security）除外。

        Args:
            name: Hook 名称
            context: Hook 上下文，可选
        """
        ctx = context or HookContext()
        is_security = name.startswith("before_") and "security" in name.lower()

        for callback in self._hooks.get(name, []):
            try:
                callback(ctx)
            except Exception as e:
                if is_security:
                    raise  # 安全校验失败必须拒绝
                logger.warning("Hook %s 执行异常: %s", name, e)
