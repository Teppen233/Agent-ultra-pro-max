from __future__ import annotations

import asyncio
from pathlib import Path

from reviewcrew.profile.indexer import RepoIndex
from reviewcrew.signals.base import run_command


class Toolbox:
    def __init__(self, repo_path: Path, index: RepoIndex) -> None:
        self.repo_path = repo_path.resolve()
        self.index = index

    def _safe_path(self, relative: str) -> Path:
        candidate = (self.repo_path / relative).resolve()
        if not candidate.is_relative_to(self.repo_path):
            raise ValueError("path escapes repository root")
        return candidate

    async def read_file(self, path: str, start: int | None = None, end: int | None = None) -> str:
        target = self._safe_path(path)
        lines = await asyncio.to_thread(target.read_text, encoding="utf-8", errors="replace")
        split = lines.splitlines()
        first = max(1, start or 1)
        last = min(len(split), end or len(split))
        return "\n".join(f"{number}: {split[number - 1]}" for number in range(first, last + 1))

    async def find_references(self, symbol: str) -> list[dict[str, object]]:
        output = []
        for location in self.index.references(symbol):
            snippet = await self.read_file(location.file, location.line, location.line)
            output.append({**location.model_dump(), "code_snippet": snippet})
        return output

    async def get_callers(self, function: str) -> list[dict[str, object]]:
        return [node.model_dump() for node in self.index.callers(function, hops=2)]

    async def get_callees(self, function: str) -> list[dict[str, object]]:
        return [node.model_dump() for node in self.index.callees(function, hops=2)]

    async def git_blame(self, path: str, start: int, end: int) -> str:
        self._safe_path(path)
        result = await run_command(
            ["git", "blame", "-L", f"{start},{end}", "--", path], self.repo_path, 30
        )
        return result.stdout if result.returncode == 0 else result.stderr

    async def run_semgrep_rule(self, rule_id: str, path: str) -> str:
        self._safe_path(path)
        result = await run_command(
            ["semgrep", "--config", rule_id, "--json", "--", path], self.repo_path, 60
        )
        return result.stdout if result.returncode in {0, 1} else result.stderr
