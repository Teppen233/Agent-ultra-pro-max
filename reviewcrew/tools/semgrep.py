"""可选的 Semgrep 静态信号 Provider。"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from reviewcrew.schemas import StaticSignal


async def run_semgrep(repo: Path, files: list[str], timeout: float = 60) -> list[StaticSignal]:
    """定向扫描修改文件；程序缺失或失败时返回空信号。"""

    executable = shutil.which("semgrep")
    if executable is None or not files:
        return []
    process = await asyncio.create_subprocess_exec(
        executable,
        "--config",
        "auto",
        "--json",
        *files,
        cwd=Path(repo),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return []
    if process.returncode not in (0, 1):
        return []
    try:
        payload = json.loads(stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return []
    signals: list[StaticSignal] = []
    for result in payload.get("results", []):
        extra = result.get("extra", {})
        severity = str(extra.get("severity", "info")).lower()
        if severity not in {"critical", "high", "medium", "low", "info"}:
            severity = "info"
        signals.append(
            StaticSignal(
                provider="semgrep",
                rule_id=result.get("check_id", "unknown"),
                file=result.get("path", ""),
                line=max(1, int(result.get("start", {}).get("line", 1))),
                message=extra.get("message", "Semgrep 检测到静态信号"),
                severity=severity,
            )
        )
    return signals

