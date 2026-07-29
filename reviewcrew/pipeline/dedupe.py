"""确定性去重模块 —— 合并重复和重叠的候选 Finding。

不依赖 LLM 或 embedding，基于文件、行号和类别的纯逻辑比较。
"""

from __future__ import annotations

from ..schemas import Finding


def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """检查两个行号区间是否重叠。"""
    return a_start <= b_end and b_start <= a_end


def deduplicate_findings(findings: list[Finding]) -> list[Finding]:
    """对候选 Finding 列表进行确定性去重。

    去重规则：
    - 同文件、同类别、行号区间重叠 → 合并为一个，保留更高置信度
    - 不同类别、不同文件 → 各自保留
    - 合并结果保留更高置信度 Finding 的完整信息

    Args:
        findings: 待去重的候选 Finding 列表

    Returns:
        去重后的 Finding 列表
    """
    if not findings:
        return []

    # 按 (file, category) 分组
    groups: dict[tuple[str, str], list[Finding]] = {}
    for f in findings:
        key = (f.file, f.category)
        groups.setdefault(key, []).append(f)

    result: list[Finding] = []

    for (file, category), group in groups.items():
        if len(group) == 1:
            result.append(group[0])
            continue

        # 按 confidence 降序排列
        sorted_group = sorted(group, key=lambda x: x.confidence, reverse=True)
        merged: list[Finding] = []
        used: set[int] = set()

        for i, f1 in enumerate(sorted_group):
            if i in used:
                continue
            best = f1
            for j, f2 in enumerate(sorted_group[i + 1 :], start=i + 1):
                if j in used:
                    continue
                if _overlap(best.line_start, best.line_end, f2.line_start, f2.line_end):
                    used.add(j)
                    # best 已经是高置信度的（sorted_group 按 confidence 降序）
            merged.append(best)
            used.add(i)

        result.extend(merged)

    return result
