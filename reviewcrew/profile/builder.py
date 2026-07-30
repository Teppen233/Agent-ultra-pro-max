from __future__ import annotations

import argparse
import threading
from pathlib import Path

from pydantic import BaseModel

from reviewcrew.profile.bug_miner import mine_bug_patterns
from reviewcrew.profile.indexer import RepoIndex, detect_languages
from reviewcrew.profile.summarizer import summarize_architecture

_PROFILE_BUILD_LOCK = threading.Lock()


class RepoProfile(BaseModel):
    repo_path: Path
    index_path: Path
    arch_summary_path: Path
    bug_patterns_path: Path

    def arch_slice(self, paths: list[str], max_chars: int = 8000) -> str:
        summary = self.arch_summary_path.read_text(encoding="utf-8", errors="replace")
        relevant = [
            line
            for line in summary.splitlines()
            if any(path.split("/")[0] in line for path in paths)
        ]
        return ("\n".join(relevant) or summary)[:max_chars]


def build_profile(repo_path: Path, changed_files: list[str] | None = None) -> RepoProfile:
    with _PROFILE_BUILD_LOCK:
        return _build_profile(repo_path, changed_files)


def _build_profile(repo_path: Path, changed_files: list[str] | None = None) -> RepoProfile:
    profile_dir = repo_path / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    index_path = profile_dir / "symbols.db"
    if changed_files:
        if index_path.exists():
            RepoIndex(index_path, repo_path).update_incremental(changed_files)
        else:
            RepoIndex.build_selected(repo_path, changed_files)
    else:
        RepoIndex.build(repo_path, detect_languages(repo_path))

    architecture_path = profile_dir / "architecture.md"
    bug_patterns_path = profile_dir / "bug_patterns.md"
    architecture_path.write_text(summarize_architecture(repo_path), encoding="utf-8")
    patterns = mine_bug_patterns(repo_path)
    bug_patterns_path.write_text(
        "# Historical Bug Patterns\n\n" + "\n".join(f"- {item}" for item in patterns) + "\n",
        encoding="utf-8",
    )
    return RepoProfile(
        repo_path=repo_path,
        index_path=index_path,
        arch_summary_path=architecture_path,
        bug_patterns_path=bug_patterns_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["update"])
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--changed", nargs="*", default=[])
    args = parser.parse_args()
    profile = build_profile(args.repo, args.changed or None)
    print(profile.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
