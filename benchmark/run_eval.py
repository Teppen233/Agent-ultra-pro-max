from __future__ import annotations

import argparse
import json
import random
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from benchmark.judge import (
    DatasetEntry,
    SemanticMatcher,
    build_llm_semantic_matcher,
    judge,
    load_dataset,
)
from benchmark.report import build_summary
from reviewcrew.cli import CLIReviewRunner
from reviewcrew.models import Finding


class ReviewRunner(Protocol):
    def review(self, pr_url: str, repo_path: Path) -> list[Finding]: ...


class FakeRunner:
    def review(self, pr_url: str, repo_path: Path) -> list[Finding]:
        seed = f"{pr_url}:{repo_path}"
        rng = random.Random(seed)
        return [
            Finding(
                id=f"fake-{index}",
                category="logic",
                severity="medium",
                confidence=0.65,
                file="src/example.py",
                line_start=10 + index,
                line_end=10 + index,
                title="Synthetic evaluation finding",
                reasoning="Generated only to validate the evaluation harness.",
                trigger_path="Synthetic runner",
                suggestion="Use a real ReviewRunner for benchmark results.",
            )
            for index in range(rng.randint(3, 5))
        ]


def evaluate(
    entries: list[DatasetEntry],
    runner: ReviewRunner,
    repos_dir: Path,
    output_dir: Path,
    semantic_matcher: SemanticMatcher | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "results.jsonl"
    with results_path.open("w", encoding="utf-8") as stream:
        for entry in entries:
            started = time.monotonic()
            findings = runner.review(entry.pr_url, repos_dir / entry.repo.split("/")[-1])
            result = judge(findings, entry, semantic_matcher=semantic_matcher)
            stream.write(
                json.dumps(
                    {
                        "repo": entry.repo,
                        "pr_url": entry.pr_url,
                        "category": entry.category,
                        "hit": result.hit,
                        "reason": result.reason,
                        "finding_count": len(findings),
                        "elapsed_seconds": time.monotonic() - started,
                    }
                )
                + "\n"
            )
    build_summary(results_path, output_dir / "summary.md")
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--quick", action="store_true")
    mode.add_argument("--full", action="store_true")
    parser.add_argument("--runner", choices=["fake", "real"], default="fake")
    parser.add_argument("--dataset", type=Path, default=Path("benchmark/dataset.yaml"))
    args = parser.parse_args()
    entries = load_dataset(args.dataset)
    if not entries:
        parser.error("dataset contains no authorized benchmark entries")
    if args.quick:
        entries = entries[:10]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    runner: ReviewRunner = CLIReviewRunner() if args.runner == "real" else FakeRunner()
    semantic_matcher = build_llm_semantic_matcher() if args.runner == "real" else None
    output = evaluate(
        entries,
        runner,
        Path("repos"),
        Path("benchmark/results") / timestamp,
        semantic_matcher,
    )
    print(output)


if __name__ == "__main__":
    main()
