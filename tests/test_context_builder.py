"""Diff 中心上下文构建测试。"""

from pathlib import Path

import pytest

from reviewcrew.config import Config
import reviewcrew.context.builder as context_builder_module
from reviewcrew.context.builder import build_context
from reviewcrew.diff.parser import parse_unified_diff
from reviewcrew.events import EventStore
from reviewcrew.schemas import PRData
from reviewcrew.tool_activity import ToolActivityPublisher


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

TYPESCRIPT_DIFF = """diff --git a/packages/auth/session.ts b/packages/auth/session.ts
index 1111111..2222222 100644
--- a/packages/auth/session.ts
+++ b/packages/auth/session.ts
@@ -1 +1,3 @@
-export const getCalendar = repository.get;
+export async function getCalendar(calendarId: string) {
+  return repository.get(calendarId);
+}
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


@pytest.mark.asyncio
async def test_build_context_collects_bounded_cross_file_symbol_references(tmp_path: Path) -> None:
    """声明型修改应检索跨文件调用入口，并排除当前修改文件与重复结果。"""

    changed = tmp_path / "packages/auth/session.ts"
    changed.parent.mkdir(parents=True)
    changed.write_text(
        "export async function getCalendar(calendarId: string) {\n"
        "  return repository.get(calendarId);\n}\n",
        encoding="utf-8",
    )
    caller = tmp_path / "apps/web/api/calendar.ts"
    caller.parent.mkdir(parents=True)
    caller.write_text(
        "export async function handler(calendarId: string) {\n"
        "  return getCalendar(calendarId);\n}\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("调用 getCalendar 获取日历。\n", encoding="utf-8")
    pr = PRData(
        provider="local",
        repository="calcom-demo",
        title="调整日历读取",
        base_sha="base",
        head_sha="head",
        files=parse_unified_diff(TYPESCRIPT_DIFF),
        raw_diff=TYPESCRIPT_DIFF,
    )

    pack = (await build_context(pr, tmp_path, Config(context_character_budget=20_000)))[0]

    assert pack.related_code
    assert {item.file for item in pack.related_code} == {"apps/web/api/calendar.ts"}
    assert any(item.start_line <= 2 <= item.end_line for item in pack.related_code)
    assert len(pack.related_code) <= 10


@pytest.mark.asyncio
async def test_build_context_publishes_only_real_reads_searches_and_explicit_semgrep_degradation(
    tmp_path: Path,
) -> None:
    """上下文构建只为已执行动作报成功，缺失 Semgrep 必须明确降级。"""

    changed = tmp_path / "packages/auth/session.ts"
    changed.parent.mkdir(parents=True)
    changed.write_text(
        "export async function getCalendar(calendarId: string) {\n"
        "  return repository.get(calendarId);\n}\n",
        encoding="utf-8",
    )
    caller = tmp_path / "apps/web/api/calendar.ts"
    caller.parent.mkdir(parents=True)
    caller.write_text("return getCalendar(calendarId);\n", encoding="utf-8")
    tests = tmp_path / "tests/session.spec.ts"
    tests.parent.mkdir()
    tests.write_text("expect(getCalendar('1')).resolves.toBeDefined();\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("日历接口说明。\n", encoding="utf-8")
    pr = PRData(
        provider="local",
        repository="calcom-demo",
        title="调整日历读取",
        base_sha="base",
        head_sha="head",
        files=parse_unified_diff(TYPESCRIPT_DIFF),
        raw_diff=TYPESCRIPT_DIFF,
    )
    store = EventStore(tmp_path / "runs")
    run_id = store.create_run()

    await build_context(
        pr,
        tmp_path,
        Config(context_character_budget=20_000),
        activity=ToolActivityPublisher(store, run_id),
        semgrep_available=False,
    )

    events = store.read(run_id)
    completed = {
        event.data["tool_name"]
        for event in events
        if event.type == "tool.completed"
    }
    assert {
        "context.read_docs",
        "context.read_file",
        "context.find_tests",
        "context.search_symbol",
    } <= completed
    assert not any(
        event.type == "tool.completed" and event.data["tool_name"] == "static.semgrep"
        for event in events
    )
    degraded = next(
        event
        for event in events
        if event.type == "tool.failed" and event.data["tool_name"] == "static.semgrep"
    )
    assert "未安装" in degraded.data["summary"]


@pytest.mark.asyncio
async def test_build_context_marks_started_test_search_as_failed_when_real_call_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实检索抛错时必须结束为 failed，不能留下开始事件或伪造成功。"""

    (tmp_path / "service.py").write_text("def update_user(value):\n    return value\n", encoding="utf-8")
    pr = PRData(
        provider="local",
        repository="demo",
        title="校验用户输入",
        base_sha="base",
        head_sha="head",
        files=parse_unified_diff(RAW_DIFF),
        raw_diff=RAW_DIFF,
    )
    store = EventStore(tmp_path / "runs")
    run_id = store.create_run()

    def fail_search(*_: object, **__: object) -> list[object]:
        raise RuntimeError("外部细节不得公开")

    monkeypatch.setattr(context_builder_module, "find_related_tests", fail_search)

    with pytest.raises(RuntimeError, match="外部细节"):
        await build_context(
            pr,
            tmp_path,
            Config(context_character_budget=20_000),
            activity=ToolActivityPublisher(store, run_id),
            semgrep_available=False,
        )

    test_search_events = [
        event
        for event in store.read(run_id)
        if event.data.get("tool_name") == "context.find_tests"
    ]
    assert [event.type for event in test_search_events] == ["tool.started", "tool.failed"]
    assert "外部细节" not in test_search_events[-1].data["summary"]
