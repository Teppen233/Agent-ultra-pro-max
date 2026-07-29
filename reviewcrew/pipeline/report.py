"""报告生成器 —— 将 ReviewResult 渲染为 Markdown 或 JSON 报告。"""

from __future__ import annotations

from ..schemas import ReviewResult


def render_markdown(result: ReviewResult) -> str:
    """将审查结果渲染为中文 Markdown 报告。

    Args:
        result: 审查结果

    Returns:
        Markdown 格式的报告字符串
    """
    lines: list[str] = []

    # 标题
    lines.append(f"# ReviewCrew 审查报告")
    lines.append("")
    lines.append(f"**运行 ID**: `{result.run_id}`")
    lines.append(f"**状态**: {_status_label(result.status)}")
    lines.append(f"**仓库**: {result.repository}")
    lines.append(f"**Base SHA**: `{result.base_sha}`")
    lines.append(f"**Head SHA**: `{result.head_sha}`")
    lines.append(f"**耗时**: {result.elapsed_seconds:.1f} 秒")
    lines.append("")

    # 覆盖维度
    if result.coverage:
        lines.append("## 覆盖维度")
        lines.append("")
        for c in result.coverage:
            lines.append(f"- {c}")
        lines.append("")

    # Findings
    lines.append(f"## 审查发现 ({len(result.findings)} 条)")
    lines.append("")

    for i, f in enumerate(result.findings, 1):
        lines.append(f"### {i}. {f.title}")
        lines.append("")
        lines.append(f"| 属性 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| **严重度** | {_severity_label(f.severity)} |")
        lines.append(f"| **类别** | {_category_label(f.category)} |")
        lines.append(f"| **置信度** | {f.confidence:.0%} |")
        lines.append(f"| **文件** | `{f.file}` |")
        lines.append(f"| **行号** | {f.line_start}-{f.line_end} |")
        lines.append(f"| **来源** | {f.producer} |")
        lines.append("")
        lines.append(f"**描述**: {f.description}")
        lines.append("")
        lines.append(f"**触发条件**: {f.trigger_condition}")
        lines.append("")
        lines.append(f"**影响**: {f.impact}")
        lines.append("")
        if f.suggestion:
            lines.append(f"**修复建议**: {f.suggestion}")
            lines.append("")

    # 统计
    lines.append("## 统计")
    lines.append("")
    lines.append(f"- 最终 Finding: {len(result.findings)}")
    lines.append(f"- 已拒绝候选: {result.rejected_count}")
    lines.append(f"- 警告: {len(result.warnings)}")
    lines.append("")

    # 警告
    if result.warnings:
        lines.append("## 警告")
        lines.append("")
        for w in result.warnings:
            lines.append(f"- ⚠️ {w}")
        lines.append("")

    return "\n".join(lines)


def _status_label(status: str) -> str:
    """状态中文标签。"""
    return {"completed": "✅ 完成", "partial": "⚠️ 部分完成", "failed": "❌ 失败"}.get(
        status, status
    )


def _severity_label(severity: str) -> str:
    """严重度中文标签。"""
    return {
        "critical": "🔴 严重",
        "high": "🟠 高",
        "medium": "🟡 中",
        "low": "🟢 低",
    }.get(severity, severity)


def _category_label(category: str) -> str:
    """类别中文标签。"""
    return {
        "static": "静态缺陷",
        "business_logic": "业务逻辑",
        "logic": "逻辑缺陷",
        "memory": "内存/资源",
        "security": "安全漏洞",
        "architecture": "架构问题",
        "reliability": "可靠性",
    }.get(category, category)
