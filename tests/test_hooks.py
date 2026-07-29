"""Hook 管理器的容错与安全测试。"""

import pytest

from reviewcrew.hooks import HookContext, HookManager, HookName, HookRejectedError


@pytest.mark.asyncio
async def test_non_security_hook_failure_does_not_block_pipeline() -> None:
    """普通 Hook 的异常仅被记录，不阻断主流程。"""

    manager = HookManager()

    async def broken_hook(context: HookContext) -> None:
        raise RuntimeError("测试异常")

    manager.register("before_agent", broken_hook)

    await manager.run("before_agent", HookContext(role="defect"))


@pytest.mark.asyncio
async def test_security_hook_rejects_tool_path_outside_repository() -> None:
    """安全 Hook 可以拒绝越过仓库边界的工具调用。"""

    manager = HookManager()

    async def reject_escape(context: HookContext) -> None:
        if context.tool_path == "../secret.txt":
            raise HookRejectedError("工具路径超出仓库范围")

    manager.register("before_tool", reject_escape, security=True)

    with pytest.raises(HookRejectedError, match="仓库范围"):
        await manager.run(
            "before_tool",
            HookContext(role="defect", tool_name="read_file", tool_path="../secret.txt"),
        )
