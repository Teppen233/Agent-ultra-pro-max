"""Benchmark 报告生成 —— 从 JudgeResult 列表生成评测摘要。"""

from __future__ import annotations

from .models import DatasetEntry, JudgeResult


def generate_summary(
    entries: list[DatasetEntry],
    results: list[JudgeResult],
) -> dict:
    """生成评测摘要。

    Args:
        entries: 运行的案例列表
        results: 判定结果列表

    Returns:
        包含命中率、分类统计等指标的字典
    """
    total = len(entries)
    completed = len(results)
    caught = sum(1 for r in results if r.caught)
    needs_review = sum(1 for r in results if r.needs_human_review)

    catch_rate = f"{caught / completed:.0%}" if completed > 0 else "N/A"

    # 按语言统计
    by_language: dict[str, dict] = {}
    for entry, result in zip(entries, results):
        lang = entry.language
        if lang not in by_language:
            by_language[lang] = {"total": 0, "caught": 0}
        by_language[lang]["total"] += 1
        if result.caught:
            by_language[lang]["caught"] += 1

    # 按类别统计
    by_category: dict[str, dict] = {}
    for entry, result in zip(entries, results):
        cat = entry.category
        if cat not in by_category:
            by_category[cat] = {"total": 0, "caught": 0}
        by_category[cat]["total"] += 1
        if result.caught:
            by_category[cat]["caught"] += 1

    return {
        "total": total,
        "completed": completed,
        "caught": caught,
        "catch_rate": catch_rate,
        "needs_review": needs_review,
        "by_language": by_language,
        "by_category": by_category,
    }
