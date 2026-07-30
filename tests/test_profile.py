from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from reviewcrew.profile.builder import build_profile
from reviewcrew.profile.summarizer import _repository_files


def test_build_profile(tmp_path: Path) -> None:
    source = Path(__file__).parent / "fixtures" / "mini_repo"
    repo = tmp_path / "repo"
    shutil.copytree(source, repo)
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    profile = build_profile(repo)
    assert profile.index_path.exists()
    assert "Module map" in profile.arch_summary_path.read_text(encoding="utf-8")
    assert profile.bug_patterns_path.exists()


def test_repository_files_use_git_inventory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    source = repo / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    metadata = repo / ".git" / "large-generated.java"
    metadata.write_text("ignored\n", encoding="utf-8")
    profile_file = repo / "profile" / "symbols.db"
    profile_file.parent.mkdir()
    profile_file.write_text("generated\n", encoding="utf-8")

    assert _repository_files(repo) == [source]
