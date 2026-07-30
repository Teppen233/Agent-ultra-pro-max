from __future__ import annotations

import json
import logging
from pathlib import Path

from reviewcrew.models import Signal
from reviewcrew.signals.base import CommandRunner, run_command

logger = logging.getLogger(__name__)


class LinterProvider:
    def __init__(self, runner: CommandRunner = run_command, timeout: float = 60.0) -> None:
        self.runner = runner
        self.timeout = timeout

    async def scan(self, repo_path: Path, files: list[str]) -> list[Signal]:
        python_files = [path for path in files if Path(path).suffix == ".py"]
        if not python_files:
            return []
        try:
            result = await self.runner(
                ["ruff", "check", "--output-format", "json", *python_files],
                repo_path,
                self.timeout,
            )
            payload = json.loads(result.stdout or "[]")
            return [
                Signal(
                    provider="ruff",
                    rule_id=str(item.get("code", "unknown")),
                    file=str(item.get("filename", "")),
                    line=max(1, int(item.get("location", {}).get("row", 1))),
                    message=str(item.get("message", "Linter finding")),
                    severity="warning",
                )
                for item in payload
            ]
        except (OSError, TimeoutError, json.JSONDecodeError, ValueError) as error:
            logger.warning("linter scan unavailable: %s", error)
            return []
