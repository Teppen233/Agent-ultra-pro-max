from __future__ import annotations

from collections import Counter

from reviewcrew.models import Finding


def _confidence(finding: Finding) -> float:
    return (
        finding.confidence_adjusted
        if finding.confidence_adjusted is not None
        else finding.confidence
    )


def _comment(finding: Finding) -> str:
    confidence = _confidence(finding)
    return (
        f"**{finding.severity.upper()} · {finding.category} · 置信度 {confidence:.0%}**\n\n"
        f"{finding.reasoning}\n\n"
        f"**触发路径：** {finding.trigger_path}\n\n"
        f"**修复建议：** {finding.suggestion}"
    )


def generate_report(findings: list[Finding]) -> tuple[str, dict[str, list[dict[str, object]]]]:
    confirmed = [
        finding
        for finding in findings
        if finding.verdict == "keep"
        and _confidence(finding) >= 0.45
    ]
    needs_review = [
        finding
        for finding in findings
        if finding.verdict is None
        or (
            finding.verdict == "keep"
            and _confidence(finding) < 0.45
        )
    ]
    rejected = [finding for finding in findings if finding.verdict == "reject"]
    counts = Counter(finding.severity for finding in confirmed)
    lines = [
        "# ReviewCrew 代码审查报告",
        "",
        "## 审查摘要",
        "",
        f"- 候选总数：{len(findings)}",
        f"- 已确认：{len(confirmed)}",
        f"- 待人工复核：{len(needs_review)}",
        f"- Verifier 已排除：{len(rejected)}",
        f"- 严重：{counts['critical']}",
        f"- 高危：{counts['high']}",
        f"- 中危：{counts['medium']}",
        f"- 低危：{counts['low']}",
        "",
        "## 已确认问题",
        "",
    ]
    if not confirmed:
        lines.extend(["暂无已确认问题。", ""])

    def append_findings(items: list[Finding]) -> None:
        for index, finding in enumerate(items, 1):
            confidence = _confidence(finding)
            lines.extend(
                [
                    f"### {index}. {finding.title}",
                    "",
                    f"`{finding.file}:{finding.line_start}-{finding.line_end}` · "
                    f"**{finding.severity}** · 置信度 {confidence:.0%}",
                    "",
                    finding.reasoning,
                    "",
                    f"**触发路径：** {finding.trigger_path}",
                    "",
                    f"**修复建议：** {finding.suggestion}",
                    "",
                ]
            )
            if finding.verdict_reason:
                lines.extend([f"**Verifier 意见：** {finding.verdict_reason}", ""])

    append_findings(confirmed)
    lines.extend(["## 待人工复核", ""])
    if not needs_review:
        lines.extend(["暂无待人工复核候选。", ""])
    append_findings(needs_review)
    lines.extend(["## Verifier 已排除的候选", ""])
    if not rejected:
        lines.extend(["暂无已排除候选。", ""])
    append_findings(rejected)
    comments = [
        {"path": finding.file, "line": finding.line_start, "body": _comment(finding)}
        for finding in confirmed
    ]
    return "\n".join(lines).rstrip() + "\n", {"comments": comments}
