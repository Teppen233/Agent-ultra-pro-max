from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

from reviewcrew.models import Signal

logger = logging.getLogger(__name__)
REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)$")


class DepsProvider:
    def __init__(self, client: httpx.AsyncClient | None = None, timeout: float = 10.0) -> None:
        self.client = client
        self.timeout = timeout

    async def scan(self, repo_path: Path, files: list[str]) -> list[Signal]:
        requirement_files = [path for path in files if Path(path).name == "requirements.txt"]
        packages: list[tuple[str, str, str, int]] = []
        for relative in requirement_files:
            path = repo_path / relative
            if not path.is_file():
                continue
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if match := REQUIREMENT.match(line.strip()):
                    packages.append((match.group(1), match.group(2), relative, line_number))
        if not packages:
            return []

        owned_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.post(
                "https://api.osv.dev/v1/querybatch",
                json={
                    "queries": [
                        {"package": {"name": name, "ecosystem": "PyPI"}, "version": version}
                        for name, version, _, _ in packages
                    ]
                },
            )
            response.raise_for_status()
            results = response.json().get("results", [])
            signals = []
            for package, result in zip(packages, results, strict=False):
                name, _, relative, line_number = package
                for vulnerability in result.get("vulns", []):
                    signals.append(
                        Signal(
                            provider="osv",
                            rule_id=str(vulnerability.get("id", "unknown")),
                            file=relative,
                            line=line_number,
                            message=f"Known vulnerability in {name}",
                            severity="error",
                        )
                    )
            return signals
        except (httpx.HTTPError, ValueError, TimeoutError) as error:
            logger.warning("dependency audit unavailable: %s", error)
            return []
        finally:
            if owned_client:
                await client.aclose()
