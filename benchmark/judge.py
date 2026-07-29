"""三层自动命中判定 —— 文件匹配、位置匹配、语义匹配。

判定规则（与 Greptile Benchmark 对齐）：
1. 文件匹配：Finding.file 与目标文件一致
2. 位置匹配：Finding 行区间与目标区间重叠（可配置 ±10 行容差）
3. 语义匹配：Finding 描述关键词与 bug_description 交叉比对，无交叠则需人工复核
"""

from __future__ import annotations

import re

from reviewcrew.schemas import Finding, ReviewResult
from .models import DatasetEntry, JudgeResult


def _extract_keywords(text: str) -> set[str]:
    """从描述文本中提取关键词（去重小写中文/英文词）。

    简单分词策略：
    - 中文：按非中文字符分割后保留长度 >= 2 的词
    - 英文：按非字母数字分割后保留长度 >= 3 的词
    """
    keywords: set[str] = set()
    # 中文词（长度 >= 2）
    for match in re.findall(r'[一-鿿]{2,}', text):
        keywords.add(match)
    # 英文词（长度 >= 3）
    for match in re.findall(r'[a-zA-Z0-9]{4,}', text):
        keywords.add(match.lower())
    return keywords


def _is_placeholder_description(description: str) -> bool:
    """检查描述是否为占位文本（尚未填写真实内容）。"""
    stripped = description.strip()
    if not stripped:
        return True
    placeholders = [
        "待从", "TBD", "TODO", "placeholder",
        "暂未", "待补充", "待确认", "需填写",
        "待录入", "N/A",
    ]
    for ph in placeholders:
        if ph in stripped:
            return True
    return False


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
                # 第三层：语义匹配（关键词交叉比对）
                if entry.bug_description:
                    entry_keywords = _extract_keywords(entry.bug_description)
                    finding_keywords = _extract_keywords(finding.description)
                    overlap = entry_keywords & finding_keywords
                    semantic_hit = len(overlap) > 0
                    has_placeholder = _is_placeholder_description(entry.bug_description)
                else:
                    semantic_hit = False
                    has_placeholder = True

                return JudgeResult(
                    case_id=entry.id,
                    caught=True,
                    matched_finding_id=finding.id,
                    location_match=True,
                    semantic_match=semantic_hit,
                    used_line_tolerance=not exact_hit,
                    reason=f"文件: {finding.file}, 行: {finding.line_start}-{finding.line_end}, "
                    f"目标: {loc.line_start}-{loc.line_end}",
                    needs_human_review=has_placeholder or not semantic_hit,
                )

    return JudgeResult(
        case_id=entry.id,
        caught=False,
        reason="未找到匹配的 Finding",
    )
