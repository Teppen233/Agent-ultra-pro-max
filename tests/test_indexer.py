from __future__ import annotations

import shutil
from pathlib import Path

from reviewcrew.profile.indexer import RepoIndex


def copy_fixture(tmp_path: Path) -> Path:
    source = Path(__file__).parent / "fixtures" / "mini_repo"
    target = tmp_path / "repo"
    shutil.copytree(source, target)
    return target


def test_build_index_and_query_graph(tmp_path: Path) -> None:
    index = RepoIndex.build(copy_fixture(tmp_path), ["python"])
    assert index.definition("helper") is not None
    assert any(location.file == "main.py" for location in index.references("helper"))
    assert [caller.name for caller in index.callers("helper")] == ["main"]
    assert [callee.name for callee in index.callees("main")] == ["helper"]


def test_incremental_update(tmp_path: Path) -> None:
    repo = copy_fixture(tmp_path)
    index = RepoIndex.build(repo, ["python"])
    (repo / "helper.py").write_text("def changed():\n    return 'ok'\n", encoding="utf-8")
    index.update_incremental(["helper.py"])
    assert index.definition("helper") is None
    assert index.definition("changed") is not None


def test_build_selected_indexes_only_changed_files(tmp_path: Path) -> None:
    repo = copy_fixture(tmp_path)
    index = RepoIndex.build_selected(repo, ["helper.py"])

    assert index.definition("helper") is not None
    assert index.definition("main") is None


def test_java_index_uses_tree_sitter_call_graph(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "Example.java"
    source.write_text(
        """
        class Example {
            void caller() {
                callee();
            }

            void callee() {}
        }
        """,
        encoding="utf-8",
    )

    index = RepoIndex.build_selected(repo, ["Example.java"])

    assert index.definition("caller") is not None
    assert index.definition("callee") is not None
    assert [caller.name for caller in index.callers("callee")] == ["caller"]
