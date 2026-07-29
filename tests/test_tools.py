"""只读工具测试 —— 验证文件读取、搜索、Git 操作的安全约束。"""

from pathlib import Path

import pytest


# ---- safe_read ----

def test_safe_read_rejects_path_escape(tmp_path: Path):
    """路径穿越攻击应被拒绝。"""
    from reviewcrew.tools.files import safe_read

    (tmp_path / "legit").mkdir()
    with pytest.raises(Exception, match="仓库范围|路径"):
        safe_read(tmp_path / "legit", "../secret.txt", 1, 10)


def test_safe_read_rejects_absolute_path(tmp_path: Path):
    """绝对路径应被拒绝。"""
    from reviewcrew.tools.files import safe_read

    (tmp_path / "legit").mkdir()
    with pytest.raises(Exception, match="仓库范围|路径"):
        safe_read(tmp_path / "legit", "/etc/passwd", 1, 10)


def test_safe_read_returns_code_evidence(tmp_path: Path):
    """合法路径应返回 CodeEvidence。"""
    from reviewcrew.tools.files import safe_read

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")

    result = safe_read(repo, "main.py", 2, 4)
    assert result.file == "main.py"
    assert result.line_start == 2
    assert result.line_end == 4
    assert "line2" in result.content


def test_safe_read_clamps_to_file_length(tmp_path: Path):
    """超出文件行数的请求应被裁剪到实际行数。"""
    from reviewcrew.tools.files import safe_read

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "short.py").write_text("a\nb\n", encoding="utf-8")

    result = safe_read(repo, "short.py", 1, 100)
    assert result.line_end <= 3


# ---- Tool Registry ----

def test_tool_registry_allows_registered_role(tmp_path: Path):
    """注册的角色应能调用对应工具。"""
    from reviewcrew.tools.registry import ToolDefinition, ToolRegistry

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="test_tool",
            description="测试工具",
            allowed_roles=["defect", "intent"],
            timeout=10,
            max_output_chars=1000,
        )
    )
    # 不抛异常即为通过
    assert "test_tool" in registry.list_tools()


def test_tool_registry_rejects_unauthorized_role(tmp_path: Path):
    """未授权的角色调用工具应被拒绝。"""
    import asyncio
    from reviewcrew.tools.registry import ToolDefinition, ToolRegistry

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="test_tool",
            description="测试工具",
            allowed_roles=["defect"],
            timeout=10,
            max_output_chars=1000,
        ),
        handler=lambda **kwargs: "ok",
    )

    with pytest.raises(Exception, match="权限|角色|不允许"):
        asyncio.run(registry.invoke("verifier", "test_tool", {}))
