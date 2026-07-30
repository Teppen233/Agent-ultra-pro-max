from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from reviewcrew.models import Finding
from reviewcrew.pipeline.orchestrator import Orchestrator

app = typer.Typer(no_args_is_help=True, help="Diff-focused multi-agent code review")


@app.command()
def review(
    pr: Annotated[str, typer.Option("--pr", help="GitHub PR URL or local unified diff file")],
    repo_path: Annotated[Path, typer.Option("--repo-path", exists=True, file_okay=False)],
) -> None:
    result = asyncio.run(Orchestrator().review(pr, repo_path))
    typer.echo(f"Run ID: {result.run_id}")
    typer.echo(f"Findings: {len(result.findings)}")
    typer.echo(f"Elapsed: {result.elapsed_seconds:.1f}s")


class CLIReviewRunner:
    def review(self, pr_url: str, repo_path: Path) -> list[Finding]:
        return asyncio.run(Orchestrator().review(pr_url, repo_path)).findings


if __name__ == "__main__":
    app()
