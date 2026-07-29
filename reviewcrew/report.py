"""审查结果的安全持久化与中文 Markdown 报告渲染。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from reviewcrew.schemas import Finding, ReviewResult


_SEVERITY_LABELS = {
    "critical": "严重",
    "high": "高危",
    "medium": "中危",
    "low": "低危",
}
_SEVERITY_ORDER = {severity: index for index, severity in enumerate(_SEVERITY_LABELS)}
_STATUS_LABELS = {
    "completed": "已完成",
    "partial": "部分完成",
    "failed": "失败",
}


def _sorted_findings(findings: list[Finding]) -> list[Finding]:
    """按严重度、位置和标识稳定排列问题。"""

    return sorted(
        findings,
        key=lambda finding: (
            _SEVERITY_ORDER[finding.severity],
            finding.file,
            finding.line_start,
            finding.line_end,
            finding.id,
        ),
    )


def _location(finding: Finding) -> str:
    """返回便于阅读的文件行号。"""

    if finding.line_start == finding.line_end:
        return f"{finding.file}:{finding.line_start}"
    return f"{finding.file}:{finding.line_start}-{finding.line_end}"


def render_markdown(result: ReviewResult) -> str:
    """将审查结果渲染为不含 Prompt、模型响应或推理内容的中文 Markdown。"""

    findings = _sorted_findings(result.findings)
    lines = [
        "# ReviewCrew 审查报告",
        "",
        "## 概览",
        "",
        f"- 运行 ID：{result.run_id}",
        f"- 状态：{_STATUS_LABELS[result.status]}",
        f"- 仓库：{result.repository}",
        f"- 基准提交：{result.base_sha}",
        f"- 目标提交：{result.head_sha}",
        f"- 已确认问题：{len(findings)}",
        f"- 已拒绝候选：{result.rejected_count}",
        f"- 总耗时：{result.elapsed_seconds:.2f} 秒",
        "",
        "## 审查发现",
    ]

    if not findings:
        lines.extend(["", "未发现已确认的问题。"])

    for finding in findings:
        evidence = "；".join(
            f"{item.source}：{item.file}:{item.start_line}-{item.end_line}（{item.description}）"
            for item in finding.evidence
        )
        lines.extend(
            [
                "",
                f"### {_SEVERITY_LABELS[finding.severity]}：{finding.title}",
                "",
                f"- **严重度**：{_SEVERITY_LABELS[finding.severity]}",
                f"- **类别**：{finding.category}",
                f"- **位置**：{_location(finding)}",
                f"- **触发条件**：{finding.trigger_condition}",
                f"- **影响**：{finding.impact}",
                f"- **证据**：{evidence}",
                f"- **建议**：{finding.suggestion or '暂无建议'}",
                "- **Verifier 状态**：已确认（最终审查结果）",
            ]
        )

    lines.extend(["", "## 警告", ""])
    if result.warnings:
        lines.extend(f"- {warning}" for warning in result.warnings)
    else:
        lines.append("- 无")
    return "\n".join(lines) + "\n"


def _safe_payload(result: ReviewResult) -> dict[str, Any]:
    """生成可公开保存的结果快照，移除内部推理摘要。"""

    payload = result.model_dump(mode="json")
    findings = _sorted_findings(result.findings)
    payload["findings"] = []
    for finding in findings:
        finding_payload = finding.model_dump(mode="json")
        finding_payload.pop("reasoning_summary", None)
        payload["findings"].append(finding_payload)
    return payload


def _atomic_write(path: Path, content: str) -> None:
    """使用同目录临时文件与替换操作原子写入 UTF-8 文本。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary_file:
        temporary_file.write(content)
        temporary_path = Path(temporary_file.name)
    try:
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def persist_report(result: ReviewResult, runs_directory: str | Path = "runs") -> tuple[Path, Path]:
    """在 ``runs/{run_id}`` 原子保存稳定 JSON 快照及 Markdown 报告。"""

    if not result.run_id or Path(result.run_id).name != result.run_id:
        raise ValueError("运行 ID 必须是非空的单个目录名称")
    run_directory = Path(runs_directory) / result.run_id
    json_path = run_directory / "result.json"
    markdown_path = run_directory / "report.md"
    json_content = json.dumps(
        _safe_payload(result), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    _atomic_write(json_path, json_content)
    _atomic_write(markdown_path, render_markdown(result))
    return json_path, markdown_path
