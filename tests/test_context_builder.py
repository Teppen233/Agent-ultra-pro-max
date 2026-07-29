"""Diff 中心上下文构建测试。"""

from pathlib import Path

import pytest

from reviewcrew.config import Config
from reviewcrew.context.builder import build_context
from reviewcrew.diff.parser import parse_unified_diff
from reviewcrew.schemas import PRData


RAW_DIFF = """diff --git a/service.py b/service.py
index 1111111..2222222 100644
--- a/service.py
+++ b/service.py
@@ -1,3 +1,4 @@
 def update_user(value):
-    return value
+    checked = validate(value)
+    return checked
"""


@pytest.mark.asyncio
async def test_build_context_collects_code_tests_and_docs(tmp_path: Path) -> None:
    """ContextPack 应包含修改代码、相关测试和项目文档。"""

    (tmp_path / "service.py").write_text(
        "def update_user(value):\n    checked = validate(value)\n    return checked\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_service.py").write_text(
        "def test_update_user():\n    assert True\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("用户更新必须先校验输入。\n", encoding="utf-8")
    pr = PRData(
        provider="local",
        repository="demo",
        title="校验用户输入",
        description="增加更新校验",
        base_sha="base",
        head_sha="head",
        files=parse_unified_diff(RAW_DIFF),
        raw_diff=RAW_DIFF,
    )

    packs = await build_context(pr, tmp_path, Config(context_character_budget=10_000))

    assert packs[0].enclosing_code[0].file == "service.py"
    assert packs[0].related_tests[0].file == "tests/test_service.py"
    assert packs[0].project_docs[0].title == "README.md"


@pytest.mark.asyncio
async def test_build_context_marks_truncation(tmp_path: Path) -> None:
    """超过字符预算时必须标记裁剪。"""

    (tmp_path / "service.py").write_text("x = 1\n" * 100, encoding="utf-8")
    pr = PRData(
        provider="local",
        repository="demo",
        title="修改",
        base_sha="base",
        head_sha="head",
        files=parse_unified_diff(RAW_DIFF),
        raw_diff=RAW_DIFF,
    )

    packs = await build_context(pr, tmp_path, Config(context_character_budget=20))

    assert packs[0].truncated is True

