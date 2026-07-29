"""Benchmark 数据模型 —— DatasetEntry 和 JudgeResult。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BugLocation(BaseModel):
    """目标漏洞位置。"""

    path: str = Field(description="文件路径")
    line_start: int = Field(description="起始行号")
    line_end: int = Field(description="结束行号")


class DatasetEntry(BaseModel):
    """Benchmark 案例定义 —— 一个已知漏洞的完整信息。"""

    id: str = Field(description="案例 ID，如 sentry-01")
    language: str = Field(description="编程语言")
    upstream_repo: str = Field(description="上游仓库 URL")
    fork_repo: str = Field(description="团队 Fork 仓库 URL")
    source_fix_pr: str = Field(description="原始修复 PR URL")
    test_pr: str = Field(description="测试 PR URL")
    base_sha: str = Field(description="漏洞引入前提交")
    head_sha: str = Field(description="包含漏洞的提交")
    introducing_commit: str = Field(description="漏洞引入提交")
    fixing_commit: str = Field(description="漏洞修复提交")
    title: str = Field(description="案例标题")
    bug_description: str = Field(description="已知漏洞描述")
    severity: str = Field(default="high", description="严重度")
    category: str = Field(default="logic", description="缺陷类别")
    bug_locations: list[BugLocation] = Field(default_factory=list, description="预期命中位置")
    status: str = Field(default="needs_review", description="状态: ready | needs_review | unavailable")


class JudgeResult(BaseModel):
    """自动判定结果 —— 文件、位置、语义三层命中判定。"""

    case_id: str = Field(description="案例 ID")
    caught: bool = Field(description="是否命中")
    matched_finding_id: str | None = Field(default=None, description="命中的 Finding ID")
    location_match: bool = Field(default=False, description="位置是否匹配")
    semantic_match: bool = Field(default=False, description="语义是否匹配")
    used_line_tolerance: bool = Field(default=False, description="是否使用了行号容差")
    reason: str = Field(default="", description="判定理由（中文）")
    needs_human_review: bool = Field(default=False, description="是否需要人工复核")
