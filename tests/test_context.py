from __future__ import annotations

import shutil
from pathlib import Path

from reviewcrew.models import FileDiff, Hunk
from reviewcrew.pipeline.context import PRMeta, build_context_packs, estimate_tokens
from reviewcrew.profile.builder import RepoProfile
from reviewcrew.profile.indexer import RepoIndex


def diff(path: str) -> FileDiff:
    return FileDiff(
        path=path,
        change_type="modify",
        hunks=[Hunk(old_start=1, old_count=1, new_start=1, new_count=1, lines=["-a", "+b"])],
    )


def setup_profile(tmp_path: Path) -> tuple[RepoIndex, RepoProfile]:
    source = Path(__file__).parent / "fixtures" / "mini_repo"
    repo = tmp_path / "repo"
    shutil.copytree(source, repo)
    (repo / "src/auth").mkdir(parents=True)
    (repo / "src/api").mkdir(parents=True)
    for relative in ("src/auth/login.py", "src/auth/logout.py", "src/api/users.py"):
        (repo / relative).write_text("value = 1\n", encoding="utf-8")
    index = RepoIndex.build(repo, ["python"])
    profile_dir = repo / "profile"
    architecture = profile_dir / "architecture.md"
    bugs = profile_dir / "bug_patterns.md"
    architecture.write_text("# Architecture\n- src/auth\n- src/api\n", encoding="utf-8")
    bugs.write_text("# Patterns\n", encoding="utf-8")
    return index, RepoProfile(
        repo_path=repo,
        index_path=index.db_path,
        arch_summary_path=architecture,
        bug_patterns_path=bugs,
    )


def test_clustering_and_intent(tmp_path: Path) -> None:
    index, profile = setup_profile(tmp_path)
    packs = build_context_packs(
        [diff("src/auth/login.py"), diff("src/auth/logout.py"), diff("src/api/users.py")],
        index,
        profile,
        [],
        PRMeta(title="Fix SQL injection", test_changes="Added escape test"),
    )
    assert len(packs) == 2
    auth = next(pack for pack in packs if pack.pack_id == "auth")
    assert len(auth.diff_hunks) == 2
    assert "SQL injection" in auth.intent
    assert estimate_tokens(auth.model_dump_json()) <= 32_000
