from __future__ import annotations

from pathlib import Path

import pytest

from reviewcrew.profile.indexer import RepoIndex
from reviewcrew.tools.toolbox import Toolbox


async def test_read_file_is_line_numbered(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    toolbox = Toolbox(tmp_path, RepoIndex.build(tmp_path, ["python"]))
    assert await toolbox.read_file("a.py", 2, 3) == "2: two\n3: three"


async def test_read_file_rejects_traversal(tmp_path: Path) -> None:
    toolbox = Toolbox(tmp_path, RepoIndex.build(tmp_path, ["python"]))
    with pytest.raises(ValueError, match="escapes"):
        await toolbox.read_file("../secret")
