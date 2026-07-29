"""三层自动命中判定 —— 文件匹配、位置匹配、语义匹配。

判定规则（与 Greptile Benchmark 对齐）：
1. 文件匹配：Finding.file 与目标文件一致
2. 位置匹配：Finding 行区间与目标区间重叠（可配置 ±10 行容差）
3. 语义匹配：Finding 必须描述同一个错误机制和实际影响
"""

from __future__ import annotations

from reviewcrew.schemas import Finding, ReviewResult
from .models import DatasetEntry, JudgeResult


def judge_case(entry: DatasetEntry, result: ReviewResult) -> JudgeResult:
    """对单个案例进行三层命中判定。

    自动判定时语义匹配默认需要人工复核。

    Args:
        entry: Benchmark 案例定义
        result: 审查结果

    Returns:
        判定结果
    """
    if entry.status != "ready":
        return JudgeResult(
            case_id=entry.id,
            caught=False,
            reason=f"案例状态为 {entry.status}，未运行判定",
        )

    for finding in result.findings:
        # 第一层：文件匹配
        target_files = {loc.path for loc in entry.bug_locations}
        if finding.file not in target_files:
            continue

        # 第二层：位置匹配（含容差）
        for loc in entry.bug_locations:
            if loc.path != finding.file:
                continue

            tolerance = 10
            f_start = finding.line_start
            f_end = finding.line_end
            t_start = loc.line_start - tolerance
            t_end = loc.line_end + tolerance

            location_hit = f_start <= t_end and t_start <= f_end
            exact_hit = (
                finding.line_start <= loc.line_end
                and loc.line_start <= finding.line_end
            )

            if location_hit:
                # 第三层：语义匹配（默认需人工复核）
                return JudgeResult(
                    case_id=entry.id,
                    caught=True,
                    matched_finding_id=finding.id,
                    location_match=True,
                    semantic_match=True,  # 假设通过（需人工复核）
                    used_line_tolerance=not exact_hit,
                    reason=f"文件: {finding.file}, 行: {finding.line_start}-{finding.line_end}, "
                    f"目标: {loc.line_start}-{loc.line_end}",
                    needs_human_review=True,
                )

    return JudgeResult(
        case_id=entry.id,
        caught=False,
        reason="未找到匹配的 Finding",
    )
