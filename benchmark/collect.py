from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, RootModel

from benchmark.judge import BugLocation, DatasetEntry
from reviewcrew.models import Category, Severity
from reviewcrew.pipeline.diff_parser import parse_diff


class SourceCase(BaseModel):
    title: str
    bug_desc: str
    severity: str
    pr_url: str


class SourceCases(RootModel[dict[str, list[SourceCase]]]):
    pass


class PullMetadata(BaseModel):
    pr_url: str
    base_sha: str
    head_sha: str
    fork_url: str


class PullMetadataList(RootModel[list[PullMetadata]]):
    pass


def _git(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo_slug(pr_url: str) -> str:
    parts = urlparse(pr_url).path.strip("/").split("/")
    if len(parts) < 4 or parts[2] != "pull":
        raise ValueError(f"unsupported pull request URL: {pr_url}")
    return f"{parts[0]}/{parts[1]}"


def _severity(value: str) -> Severity:
    normalized = value.lower()
    if normalized not in {"critical", "high", "medium", "low"}:
        raise ValueError(f"unsupported severity: {value}")
    return cast(Severity, normalized)


def _category(description: str) -> Category:
    value = description.lower()
    if any(
        marker in value
        for marker in (
            "injection",
            "ssrf",
            "timing attack",
            "permission",
            "backup codes",
            "blacklist",
        )
    ):
        return "security"
    if any(marker in value for marker in ("non-existent", "compilation", "only contains pass")):
        return "static"
    return "logic"


def _bug_locations(raw_diff: str) -> list[BugLocation]:
    locations: list[BugLocation] = []
    for file_diff in parse_diff(raw_diff):
        if not file_diff.hunks:
            continue
        line_start = max(1, min(hunk.new_start for hunk in file_diff.hunks))
        line_end = max(
            max(1, hunk.new_start) + max(hunk.new_count, 1) - 1
            for hunk in file_diff.hunks
        )
        locations.append(
            BugLocation(path=file_diff.path, line_start=line_start, line_end=line_end)
        )
    if not locations:
        raise ValueError("pull request contains no evaluable code hunks")
    return locations


def build_dataset(
    source_path: Path,
    metadata_path: Path,
    repos_dir: Path,
    diffs_dir: Path | None = None,
) -> list[DatasetEntry]:
    source = SourceCases.model_validate_json(source_path.read_text(encoding="utf-8")).root
    metadata = PullMetadataList.model_validate_json(
        metadata_path.read_text(encoding="utf-8")
    ).root
    metadata_by_url = {item.pr_url: item for item in metadata}
    entries: list[DatasetEntry] = []
    for cases in source.values():
        for case in cases:
            pull = metadata_by_url.get(case.pr_url)
            if pull is None:
                raise ValueError(f"missing pull request metadata: {case.pr_url}")
            repo = _repo_slug(case.pr_url)
            repo_path = repos_dir / repo.split("/")[-1]
            if not repo_path.is_dir():
                raise FileNotFoundError(f"missing local repository: {repo_path}")
            _git(repo_path, "cat-file", "-e", f"{pull.base_sha}^{{commit}}")
            _git(repo_path, "cat-file", "-e", f"{pull.head_sha}^{{commit}}")
            raw_diff = _git(
                repo_path,
                "diff",
                "--binary",
                "--find-renames",
                f"{pull.base_sha}...{pull.head_sha}",
            )
            diff_path: Path | None = None
            if diffs_dir is not None:
                pr_number = case.pr_url.rstrip("/").rsplit("/", 1)[-1]
                diff_path = diffs_dir / repo.split("/")[-1] / f"pr-{pr_number}.diff"
                diff_path.parent.mkdir(parents=True, exist_ok=True)
                diff_path.write_text(raw_diff + "\n", encoding="utf-8")
            entries.append(
                DatasetEntry(
                    repo=repo,
                    fork_url=pull.fork_url,
                    pr_url=case.pr_url,
                    base_sha=pull.base_sha,
                    head_sha=pull.head_sha,
                    diff_path=str(diff_path) if diff_path is not None else None,
                    title=case.title,
                    bug_desc=case.bug_desc,
                    bug_files=_bug_locations(raw_diff),
                    category=_category(case.bug_desc),
                    severity=_severity(case.severity),
                )
            )
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the local Greptile benchmark dataset.")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("benchmark/greptile_cases.json"),
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("benchmark/greptile_pr_metadata.json"),
    )
    parser.add_argument("--repos-dir", type=Path, default=Path("repos"))
    parser.add_argument("--diffs-dir", type=Path, default=Path("benchmark/diffs"))
    parser.add_argument("--output", type=Path, default=Path("benchmark/dataset.yaml"))
    args = parser.parse_args()
    entries = build_dataset(args.source, args.metadata, args.repos_dir, args.diffs_dir)
    payload = [entry.model_dump(mode="json", exclude_none=True) for entry in entries]
    args.output.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.repo] = counts.get(entry.repo, 0) + 1
    print(json.dumps({"entries": len(entries), "repos": counts}, indent=2))


if __name__ == "__main__":
    main()
