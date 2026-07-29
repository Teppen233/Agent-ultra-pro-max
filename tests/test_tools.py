"""只读仓库工具测试。"""

import subprocess
from pathlib import Path

import pytest

from reviewcrew.tools.files import ToolAccessError, safe_read
from reviewcrew.tools.git import git_history
from reviewcrew.tools.search import find_related_tests, search_code
from reviewcrew.tools.semgrep import run_semgrep


def test_safe_read_rejects_path_escape(tmp_path: Path) -> None:
    """文件工具必须拒绝跳出仓库的路径。"""

    with pytest.raises(ToolAccessError, match="仓库范围"):
        safe_read(tmp_path, "../secret.txt", 1, 10)


def test_safe_read_returns_requested_range(tmp_path: Path) -> None:
    """读取结果必须带有精确行号。"""

    (tmp_path / "app.py").write_text("一\n二\n三\n", encoding="utf-8")

    evidence = safe_read(tmp_path, "app.py", 2, 3)

    assert evidence.start_line == 2
    assert evidence.content == "二\n三"


def test_search_code_and_related_tests_are_bounded(tmp_path: Path) -> None:
    """代码搜索和测试发现应返回受限证据。"""

    (tmp_path / "service.py").write_text("def update_user():\n    pass\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_service.py").write_text("def test_update_user():\n    pass\n", encoding="utf-8")

    assert search_code(tmp_path, "update_user", limit=1)[0].file == "service.py"
    assert find_related_tests(tmp_path, "service.py")[0].file == "tests/test_service.py"


def test_git_history_returns_commit_summary(tmp_path: Path) -> None:
    """Git 历史工具应返回中文说明和提交引用。"""

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "测试用户"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "添加配置"], cwd=tmp_path, check=True, capture_output=True)

    history = git_history(tmp_path, "app.py", limit=2)

    assert history[0].title == "添加配置"


@pytest.mark.asyncio
async def test_semgrep_missing_returns_empty_signals(tmp_path: Path, monkeypatch) -> None:
    """Semgrep 不存在时必须安全降级。"""

    monkeypatch.setattr("reviewcrew.tools.semgrep.shutil.which", lambda _: None)

    assert await run_semgrep(tmp_path, ["app.py"], timeout=1) == []

