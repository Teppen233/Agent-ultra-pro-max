"""对 Verifier 最终接受的 Finding 执行三层 Benchmark 判定。"""

from __future__ import annotations

from reviewcrew.schemas import Finding, ReviewResult

from benchmark.models import BugLocation, DatasetEntry, JudgeResult


def _line_distance(finding: Finding, target: BugLocation) -> int:
    """返回两个闭区间的最短行距；重叠时为零。"""

    if finding.line_end < target.start_line:
        return target.start_line - finding.line_end
    if target.end_line < finding.line_start:
        return finding.line_start - target.end_line
    return 0


def _semantic_match(entry: DatasetEntry, finding: Finding) -> bool:
    """要求 Finding 同时明确覆盖预先人工标注的错误机制与实际影响。"""

    text = "\n".join(
        (
            finding.title,
            finding.description,
            finding.trigger_condition,
            finding.impact,
        )
    ).casefold()
    mechanism_match = all(keyword.casefold() in text for keyword in entry.mechanism_keywords)
    impact_match = all(keyword.casefold() in text for keyword in entry.impact_keywords)
    return mechanism_match and impact_match


def judge_case(entry: DatasetEntry, result: ReviewResult) -> JudgeResult:
    """按文件、位置和语义依次裁决；只检查 Verifier 已发布的最终 findings。"""

    accepted = result.findings
    failure_layer = "Verifier"
    deepest_failure = 0
    best_location_tolerance: int | None = None
    matches: list[tuple[Finding, int]] = []
    false_positive_count = 0
    for finding in accepted:
        same_file = [target for target in entry.bug_locations if target.file == finding.file]
        if not same_file:
            false_positive_count += 1
            if deepest_failure < 1:
                failure_layer = "文件"
                deepest_failure = 1
            continue
        distances = [(target, _line_distance(finding, target)) for target in same_file]
        eligible = [(target, distance) for target, distance in distances if distance <= entry.line_tolerance]
        if not eligible:
            false_positive_count += 1
            if deepest_failure < 2:
                failure_layer = "位置"
                deepest_failure = 2
            continue
        used_tolerance = min(distance for _, distance in eligible)
        if best_location_tolerance is None or used_tolerance < best_location_tolerance:
            best_location_tolerance = used_tolerance
        if not _semantic_match(entry, finding):
            false_positive_count += 1
            failure_layer = "语义"
            deepest_failure = 3
            continue
        matches.append((finding, used_tolerance))
    if matches:
        matched_finding, matched_tolerance = matches[0]
        return JudgeResult(
            caught=True,
            matched_finding_id=matched_finding.id,
            location_match=True,
            semantic_match=True,
            used_line_tolerance=matched_tolerance,
            needs_human_review=result.status != "completed",
            reason="Verifier 接受 Finding 已通过文件、位置与语义三层匹配。",
            false_positive_count=false_positive_count,
            verifier_accepted_count=len(accepted),
            verifier_rejected_count=result.rejected_count,
        )
    return JudgeResult(
        caught=False,
        matched_finding_id=None,
        location_match=best_location_tolerance is not None,
        semantic_match=False,
        used_line_tolerance=best_location_tolerance,
        needs_human_review=result.status != "completed",
        reason=(
            "没有 Verifier 接受的 Finding，拒绝项不会被 Judge 恢复为命中。"
            if not accepted
            else f"Verifier 接受 Finding 未通过{failure_layer}层匹配。"
        ),
        false_positive_count=false_positive_count,
        verifier_accepted_count=len(accepted),
        verifier_rejected_count=result.rejected_count,
    )
