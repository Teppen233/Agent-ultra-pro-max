"""上下文构建器测试 —— 验证 ContextPack 组装和字符预算裁剪。"""

from pathlib import Path

import pytest
from reviewcrew.schemas import PRData, ChangedFile, DiffHunk


def make_pr_data(repo_path: Path, files: list[ChangedFile] | None = None) -> PRData:
    """创建测试用 PRData。"""
    if files is None:
        files = [
            ChangedFile(
                path="src/main.py",
                status="modified",
                additions=2,
                deletions=0,
                hunks=[
                    DiffHunk(
                        id="h1",
                        file="src/main.py",
                        old_start=1,
                        old_count=3,
                        new_start=1,
                        new_count=5,
                        changed_lines=[2, 3],
                        content="+def new_func():\n+    pass",
                    )
                ],
            )
        ]
    return PRData(
        provider="local",
        repository=str(repo_path),
        title="测试 PR",
        description="测试用",
        base_sha="abc",
        head_sha="def",
        files=files,
        raw_diff="",
    )


@pytest.mark.asyncio
async def test_context_builder_creates_packs_for_modified_files(tmp_path: Path):
    """Context Builder 应为每个修改文件创建 ContextPack。"""
    from reviewcrew.config import Config
    from reviewcrew.context.builder import build_context

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "main.py").write_text("def old():\n    pass\n", encoding="utf-8")

    pr = make_pr_data(tmp_path / "repo")
    config = Config.from_env()
    packs = await build_context(pr, repo, config)

    assert len(packs) >= 1
    assert packs[0].files == ["src/main.py"]


@pytest.mark.asyncio
async def test_context_builder_includes_diff_hunks(tmp_path: Path):
    """ContextPack 应包含 diff hunk 信息。"""
    from reviewcrew.config import Config
    from reviewcrew.context.builder import build_context

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "main.py").write_text("def old():\n    pass\n", encoding="utf-8")

    pr = make_pr_data(tmp_path / "repo")
    config = Config.from_env()
    packs = await build_context(pr, repo, config)

    assert len(packs[0].diff_hunks) == 1
    assert packs[0].diff_hunks[0].file == "src/main.py"


@pytest.mark.asyncio
async def test_context_builder_truncates_on_budget(tmp_path: Path):
    """超过字符预算时应标记 truncated=True。"""
    from reviewcrew.config import Config
    from reviewcrew.context.builder import build_context

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir(parents=True)
    # 创建一个大文件，有大量修改行分布在文件中
    huge_content = "def func():\n" + "    x = 'a' * 100\n" * 200
    (repo / "src" / "main.py").write_text(huge_content, encoding="utf-8")

    pr = make_pr_data(
        tmp_path / "repo",
        files=[
            ChangedFile(
                path="src/main.py",
                status="modified",
                additions=50,
                deletions=10,
                hunks=[
                    DiffHunk(
                        id="h1",
                        file="src/main.py",
                        old_start=1,
                        old_count=100,
                        new_start=1,
                        new_count=150,
                        changed_lines=list(range(10, 200)),  # 大量变更行
                        content="...",
                    )
                ],
            )
        ],
    )
    config = Config.from_env()
    config.context_pack_char_budget = 200  # 很小的预算
    packs = await build_context(pr, repo, config)

    assert packs[0].truncated is True


@pytest.mark.asyncio
async def test_context_builder_handles_missing_files(tmp_path: Path):
    """文件缺失时应优雅降级，不抛异常。"""
    from reviewcrew.config import Config
    from reviewcrew.context.builder import build_context

    repo = tmp_path / "repo"
    repo.mkdir()

    pr = make_pr_data(tmp_path / "repo")
    config = Config.from_env()

    # 不应抛异常
    packs = await build_context(pr, repo, config)
    assert len(packs) >= 0
