from __future__ import annotations

import json
from pathlib import Path

from reviewcrew.signals.base import CommandResult
from reviewcrew.signals.linters import LinterProvider
from reviewcrew.signals.semgrep import SemgrepProvider


async def test_semgrep_parses_signal(tmp_path: Path) -> None:
    async def runner(command: list[str], cwd: Path, timeout: float) -> CommandResult:
        payload = {
            "results": [
                {
                    "check_id": "python.lang.security.audit.eval-detected",
                    "path": "app.py",
                    "start": {"line": 12},
                    "extra": {"message": "Avoid eval", "severity": "ERROR"},
                }
            ]
        }
        return CommandResult(1, json.dumps(payload), "")

    signals = await SemgrepProvider(runner=runner).scan(tmp_path, ["app.py"])
    assert len(signals) == 1
    assert signals[0].line == 12
    assert signals[0].severity == "error"


async def test_provider_failure_returns_empty(tmp_path: Path) -> None:
    async def runner(command: list[str], cwd: Path, timeout: float) -> CommandResult:
        raise TimeoutError

    assert await SemgrepProvider(runner=runner).scan(tmp_path, ["app.py"]) == []


async def test_linter_parses_ruff(tmp_path: Path) -> None:
    async def runner(command: list[str], cwd: Path, timeout: float) -> CommandResult:
        return CommandResult(
            1,
            json.dumps(
                [
                    {
                        "code": "F401",
                        "filename": "app.py",
                        "location": {"row": 3},
                        "message": "Unused import",
                    }
                ]
            ),
            "",
        )

    signals = await LinterProvider(runner=runner).scan(tmp_path, ["app.py"])
    assert signals[0].rule_id == "F401"
