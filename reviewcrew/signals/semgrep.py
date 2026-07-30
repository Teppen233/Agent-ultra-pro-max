from __future__ import annotations

import json
import logging
from pathlib import Path

from reviewcrew.models import Signal
from reviewcrew.signals.base import CommandRunner, run_command

logger = logging.getLogger(__name__)


class SemgrepProvider:
    def __init__(self, runner: CommandRunner = run_command, timeout: float = 60.0) -> None:
        self.runner = runner
        self.timeout = timeout

    async def scan(self, repo_path: Path, files: list[str]) -> list[Signal]:
        if not files:
            return []
        try:
            result = await self.runner(
                ["semgrep", "--config", "auto", "--json", "--quiet", *files],
                repo_path,
                self.timeout,
            )
            payload = json.loads(result.stdout or "{}")
            signals = []
            for item in payload.get("results", []):
                extra = item.get("extra", {})
                severity = str(extra.get("severity", "INFO")).lower()
                normalized = {"error": "error", "warning": "warning"}.get(severity, "info")
                signals.append(
                    Signal(
                        provider="semgrep",
                        rule_id=str(item.get("check_id", "unknown")),
                        file=str(item.get("path", "")),
                        line=max(1, int(item.get("start", {}).get("line", 1))),
                        message=str(extra.get("message", "Semgrep match")),
                        severity=normalized,
                    )
                )
            return signals
        except (OSError, TimeoutError, json.JSONDecodeError, ValueError) as error:
            logger.warning("semgrep scan unavailable: %s", error)
            return []
