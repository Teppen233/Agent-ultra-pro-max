"""Diff 解析器测试 —— 验证 unified diff 的逐行状态机解析。"""

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_diff() -> str:
    """加载 sample.diff fixture。"""
    return (FIXTURE_DIR / "sample.diff").read_text(encoding="utf-8")


# ---- 基本解析 ----

def test_parse_diff_detects_all_file_statuses(sample_diff: str):
    """应识别 added、modified、deleted 和 renamed 四种文件状态。"""
    from reviewcrew.diff.parser import parse_unified_diff

    files = parse_unified_diff(sample_diff)
    statuses = {f.path: f.status for f in files}
    assert statuses["src/main.py"] == "modified"
    assert statuses["src/utils.py"] == "added"
    assert statuses["src/old_module.py"] == "deleted"
    assert statuses["src/renamed_config.py"] == "renamed"


def test_parse_diff_tracks_only_new_changed_lines(sample_diff: str):
    """changed_lines 应只包含新文件中变更的行号（+ 行），不包含上下文行。"""
    from reviewcrew.diff.parser import parse_unified_diff

    files = parse_unified_diff(sample_diff)
    main_file = next(f for f in files if f.path == "src/main.py")
    assert len(main_file.hunks) == 1
    # 只有第 12 行（+ 行，新文件行号）是变更行
    # changed_lines 应该只包含 + 行的新文件行号
    assert len(main_file.hunks[0].changed_lines) == 2
    assert all(line > 0 for line in main_file.hunks[0].changed_lines)


def test_parse_diff_supports_renamed_file(sample_diff: str):
    """重命名文件应有 old_path 且状态为 renamed。"""
    from reviewcrew.diff.parser import parse_unified_diff

    files = parse_unified_diff(sample_diff)
    renamed = next(f for f in files if f.status == "renamed")
    assert renamed.path == "src/renamed_config.py"
    assert renamed.old_path == "src/config.py"


def test_parse_diff_new_file_has_no_old_path():
    """新增文件不应有 old_path。"""
    from reviewcrew.diff.parser import parse_unified_diff

    # 简单 diff：新增文件
    diff = """diff --git a/new.py b/new.py
new file mode 100644
index 0000000..1234567
--- /dev/null
+++ b/new.py
@@ -0,0 +1,3 @@
+def hello():
+    print("hi")
+    return True
"""
    files = parse_unified_diff(diff)
    assert len(files) == 1
    assert files[0].status == "added"
    assert files[0].old_path is None


def test_parse_diff_counts_additions_and_deletions(sample_diff: str):
    """additions 和 deletions 计数应正确。"""
    from reviewcrew.diff.parser import parse_unified_diff

    files = parse_unified_diff(sample_diff)
    renamed = next(f for f in files if f.path == "src/renamed_config.py")
    assert renamed.additions == 4  # docstring + blank + TIMEOUT=60 + MAX_RETRIES=3
    assert renamed.deletions == 1  # TIMEOUT=30


def test_parse_diff_multi_hunk_file(sample_diff: str):
    """多 hunk 文件应正确拆分。"""
    from reviewcrew.diff.parser import parse_unified_diff

    files = parse_unified_diff(sample_diff)
    complex_file = next(f for f in files if f.path == "src/complex.py")
    assert len(complex_file.hunks) == 2


def test_changed_line_set_aggregates_by_file(sample_diff: str):
    """changed_line_set 应按文件聚合所有变更行号。"""
    from reviewcrew.diff.parser import changed_line_set, parse_unified_diff

    files = parse_unified_diff(sample_diff)
    line_map = changed_line_set(files)
    assert "src/main.py" in line_map
    assert 12 in line_map["src/main.py"]


def test_parse_diff_empty_input():
    """空 diff 应返回空列表。"""
    from reviewcrew.diff.parser import parse_unified_diff

    assert parse_unified_diff("") == []


def test_parse_diff_binary_file_skipped():
    """二进制文件变更应被跳过并标记。"""
    from reviewcrew.diff.parser import parse_unified_diff

    diff = """diff --git a/image.png b/image.png
index 111..222 100644
Binary files a/image.png and b/image.png differ
"""
    files = parse_unified_diff(diff)
    assert len(files) == 0
