"""Unified Diff 解析测试。"""

from pathlib import Path

from reviewcrew.diff.parser import changed_line_set, parse_unified_diff


def sample_diff() -> str:
    """读取覆盖多种文件状态的差异样本。"""

    return Path("tests/fixtures/sample.diff").read_text(encoding="utf-8")


def test_parse_diff_tracks_only_new_changed_lines() -> None:
    """修改行集合只应包含新增侧实际变化的行。"""

    files = parse_unified_diff(sample_diff())
    app = next(item for item in files if item.path == "src/app.py")

    assert app.hunks[0].changed_lines == [11, 12]
    assert app.additions == 2
    assert app.deletions == 1


def test_parse_diff_supports_renamed_file() -> None:
    """重命名文件应同时保留新旧路径。"""

    renamed = next(item for item in parse_unified_diff(sample_diff()) if item.status == "renamed")

    assert renamed.path == "new_name.py"
    assert renamed.old_path == "old_name.py"


def test_parse_diff_supports_added_file() -> None:
    """新增文件的所有内容行都属于修改行。"""

    added = next(item for item in parse_unified_diff(sample_diff()) if item.status == "added")

    assert added.hunks[0].changed_lines == [1, 2]


def test_changed_line_set_groups_by_file() -> None:
    """修改行索引应按文件聚合。"""

    index = changed_line_set(parse_unified_diff(sample_diff()))

    assert index["src/app.py"] == {11, 12}

