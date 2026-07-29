"""对专家候选执行不依赖模型的确定性去重。"""

from __future__ import annotations

from collections import defaultdict

from reviewcrew.schemas import CodeEvidence, Finding


def deduplicate_findings(findings: list[Finding]) -> list[Finding]:
    """仅合并同文件、重叠行、同类别且同触发机制的候选。"""

    grouped: dict[tuple[str, str, str], list[Finding]] = defaultdict(list)
    for finding in findings:
        grouped[(finding.file, finding.category, _normalize_trigger(finding.trigger_condition))].append(finding)

    merged: list[Finding] = []
    for group_key in sorted(grouped):
        ordered = sorted(grouped[group_key], key=_location_key)
        cluster: list[Finding] = []
        cluster_end = -1
        for finding in ordered:
            if cluster and finding.line_start > cluster_end:
                merged.append(_merge_cluster(cluster))
                cluster = []
                cluster_end = -1
            cluster.append(finding)
            cluster_end = max(cluster_end, finding.line_end)
        if cluster:
            merged.append(_merge_cluster(cluster))
    return sorted(merged, key=_output_key)


def _normalize_trigger(trigger: str) -> str:
    """折叠无意义空白，使等价触发机制具有稳定键。"""

    return " ".join(trigger.split()).casefold()


def _location_key(finding: Finding) -> tuple[int, int, str]:
    """返回构建重叠区间簇所需的稳定顺序。"""

    return finding.line_start, finding.line_end, finding.id


def _representative_key(finding: Finding) -> tuple[float, str, int, int]:
    """优先最高置信度，平局时按标识和位置稳定选择代表。"""

    return -finding.confidence, finding.id, finding.line_start, finding.line_end


def _merge_cluster(cluster: list[Finding]) -> Finding:
    """合并一个相互连通的重叠区间簇。"""

    representative = min(cluster, key=_representative_key)
    evidence_by_key: dict[tuple[str, str, int, int, str, str, str], CodeEvidence] = {}
    for finding in cluster:
        for evidence in finding.evidence:
            evidence_by_key.setdefault(_evidence_key(evidence), evidence)
    evidence = [evidence_by_key[key] for key in sorted(evidence_by_key)]
    return representative.model_copy(update={"evidence": evidence})


def _evidence_key(evidence: CodeEvidence) -> tuple[str, str, int, int, str, str, str]:
    """返回证据去重与排序共用的完整内容键。"""

    return (
        evidence.source,
        evidence.file,
        evidence.start_line,
        evidence.end_line,
        evidence.description,
        evidence.content,
        evidence.content_hash or "",
    )

def _output_key(finding: Finding) -> tuple[str, str, int, int, str, str]:
    """返回与输入排列无关的最终输出顺序。"""

    return (
        finding.file,
        finding.category,
        finding.line_start,
        finding.line_end,
        _normalize_trigger(finding.trigger_condition),
        finding.id,
    )
