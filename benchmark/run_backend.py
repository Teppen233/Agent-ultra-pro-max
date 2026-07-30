from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx

from benchmark.judge import DatasetEntry, load_dataset


def select_entries(entries: list[DatasetEntry], per_repo: int) -> list[DatasetEntry]:
    by_repo: dict[str, list[DatasetEntry]] = {}
    repo_order: list[str] = []
    for entry in entries:
        if entry.repo not in by_repo:
            by_repo[entry.repo] = []
            repo_order.append(entry.repo)
        by_repo[entry.repo].append(entry)
    selected: list[DatasetEntry] = []
    for index in range(per_repo):
        for repo in repo_order:
            cases = by_repo[repo]
            if index < len(cases):
                selected.append(cases[index])
    return selected


def run_name(entry: DatasetEntry, index: int) -> str:
    del index
    repository = entry.repo.split("/")[-1].removesuffix("-greptile")
    pr_number = entry.pr_url.rstrip("/").rsplit("/", 1)[-1]
    title = entry.title or entry.bug_desc
    return f"Greptile {repository} PR #{pr_number} - {title}"


async def wait_for_run(client: httpx.AsyncClient, run_id: str) -> str:
    while True:
        response = await client.get("/api/runs")
        response.raise_for_status()
        run = next((item for item in response.json() if item["run_id"] == run_id), None)
        if run is not None and run["status"] in {"done", "failed"}:
            return str(run["status"])
        await asyncio.sleep(5)


async def execute(
    client: httpx.AsyncClient,
    entry: DatasetEntry,
    index: int,
    repos_dir: Path,
    runs_dir: Path,
    semaphore: asyncio.Semaphore,
) -> dict[str, str]:
    if entry.diff_path is None:
        raise ValueError(f"dataset entry has no diff_path: {entry.pr_url}")
    async with semaphore:
        name = run_name(entry, index)
        response = await client.post(
            "/api/review",
            json={
                "pr_url": str(Path(entry.diff_path).resolve()),
                "repo_path": str((repos_dir / entry.repo.split("/")[-1]).resolve()),
                "run_name": name,
            },
        )
        response.raise_for_status()
        run_id = str(response.json()["run_id"])
        metadata_path = runs_dir / run_id / "metadata.json"
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(
                {
                    "name": name,
                    "source": entry.diff_path,
                    "repo": entry.repo,
                    "pr_url": entry.pr_url,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(json.dumps({"event": "started", "run_id": run_id, "name": name}), flush=True)
        status = await wait_for_run(client, run_id)
        result = {
            "run_id": run_id,
            "name": name,
            "status": status,
            "repo": entry.repo,
            "pr_url": entry.pr_url,
        }
        print(json.dumps({"event": "finished", **result}), flush=True)
        return result


async def run(args: argparse.Namespace) -> None:
    selected_entries = select_entries(load_dataset(args.dataset), args.per_repo)
    entries = [entry for entry in selected_entries if entry.pr_url not in set(args.skip_pr_url)]
    semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(base_url=args.backend, timeout=30, trust_env=False) as client:
        tasks = [
            execute(client, entry, index, args.repos_dir, args.runs_dir, semaphore)
            for index, entry in enumerate(entries, 1)
        ]
        if args.existing_run_id:

            async def wait_existing() -> dict[str, str]:
                async with semaphore:
                    status = await wait_for_run(client, args.existing_run_id)
                    metadata_path = args.runs_dir / args.existing_run_id / "metadata.json"
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    source = metadata.get("source")
                    existing_entry = next(
                        (entry for entry in selected_entries if entry.diff_path == source),
                        None,
                    )
                    repo = metadata.get("repo") or (
                        existing_entry.repo if existing_entry is not None else None
                    )
                    pr_url = metadata.get("pr_url") or (
                        existing_entry.pr_url if existing_entry is not None else None
                    )
                    if not isinstance(repo, str) or not isinstance(pr_url, str):
                        raise ValueError(
                            f"cannot resolve benchmark identity for {args.existing_run_id}"
                        )
                    result = {
                        "run_id": args.existing_run_id,
                        "name": str(metadata["name"]),
                        "status": status,
                        "repo": repo,
                        "pr_url": pr_url,
                    }
                    print(json.dumps({"event": "finished", **result}), flush=True)
                    return result

            tasks.insert(0, wait_existing())
        results = await asyncio.gather(*tasks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run benchmark cases through the backend API.")
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--dataset", type=Path, default=Path("benchmark/dataset.yaml"))
    parser.add_argument("--repos-dir", type=Path, default=Path("repos"))
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument("--per-repo", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--skip-pr-url", action="append", default=[])
    parser.add_argument("--existing-run-id")
    parser.add_argument("--output", type=Path, default=Path("benchmark/results/backend-runs.json"))
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
