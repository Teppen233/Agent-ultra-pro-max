"""全局唯一领域模型 —— 所有公共 Pydantic Schema 的定义。

本模块不得导入项目其他模块，只使用标准库和 pydantic。
所有公开类写中文 docstring，字段名和枚举值使用英文。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


# ============================================================================
# 基础证据类型
# ============================================================================


class CodeEvidence(BaseModel):
    """代码片段证据 —— 包含文件路径、行号和内容。"""

    file: str = Field(description="文件相对路径")
    line_start: int = Field(description="起始行号（1-indexed）")
    line_end: int = Field(description="结束行号（1-indexed）")
    content: str = Field(description="代码内容")
    language: str = Field(default="", description="编程语言")


class TextEvidence(BaseModel):
    """文本证据 —— 文档、提交信息、注释等非代码文本。"""

    source: str = Field(description="来源标识，如 git-log, README 等")
    content: str = Field(description="文本内容")
    metadata: dict[str, str] = Field(default_factory=dict, description="附加元数据")


class StaticSignal(BaseModel):
    """静态分析信号 —— 来自 Semgrep 等工具的原始发现。"""

    tool: str = Field(description="工具名称，如 semgrep")
    rule_id: str = Field(description="规则 ID")
    file: str = Field(description="命中文件路径")
    line: int = Field(description="命中行号")
    message: str = Field(description="工具原始消息")
    severity: str = Field(default="warning", description="工具报告的严重度")
    confidence: float = Field(default=0.5, ge=0, le=1, description="工具报告置信度")


# ============================================================================
# Diff 相关
# ============================================================================


class DiffHunk(BaseModel):
    """单个 diff hunk —— 包含变更行号和内容。"""

    id: str = Field(description="Hunk 唯一标识")
    file: str = Field(description="所属文件路径")
    old_start: int = Field(description="旧文件起始行号")
    old_count: int = Field(description="旧文件行数")
    new_start: int = Field(description="新文件起始行号")
    new_count: int = Field(description="新文件行数")
    changed_lines: list[int] = Field(description="变更行号列表（新文件行号）")
    content: str = Field(description="Hunk 原始 diff 文本")


class ChangedFile(BaseModel):
    """PR 中变更的文件。"""

    path: str = Field(description="文件路径")
    old_path: str | None = Field(default=None, description="重命名前的旧路径")
    status: Literal["added", "modified", "deleted", "renamed"] = Field(
        description="文件变更状态"
    )
    additions: int = Field(ge=0, description="新增行数")
    deletions: int = Field(ge=0, description="删除行数")
    hunks: list[DiffHunk] = Field(default_factory=list, description="Diff hunk 列表")


# ============================================================================
# 审查请求与 PR 数据
# ============================================================================


class ReviewRequest(BaseModel):
    """审查请求 —— 支持 GitHub PR、本地仓库和 Replay 三种模式。

    三种模式互斥：
    - GitHub 模式：提供 pr_url
    - 本地模式：提供 repo_path, base_ref, head_ref
    - Replay 模式：提供 replay_run_id
    """

    pr_url: str | None = Field(default=None, description="GitHub PR URL")
    repo_path: str | None = Field(default=None, description="本地仓库路径")
    base_ref: str | None = Field(default=None, description="基准引用")
    head_ref: str | None = Field(default=None, description="目标引用")
    replay_run_id: str | None = Field(default=None, description="Replay 运行 ID")

    @model_validator(mode="after")
    def _validate_exactly_one_mode(self) -> "ReviewRequest":
        """三种模式必须且只能选择一种。"""
        modes = [
            self.pr_url is not None,
            self.repo_path is not None and self.base_ref is not None and self.head_ref is not None,
            self.replay_run_id is not None,
        ]
        active = sum(modes)
        if active == 0:
            raise ValueError(
                "必须指定一种审查模式：pr_url、本地仓库参数 (repo_path/base_ref/head_ref) 或 replay_run_id"
            )
        if active > 1:
            raise ValueError("pr_url、本地仓库参数和 replay_run_id 只能指定一种")
        return self


class PRData(BaseModel):
    """PR 数据 —— 加载器产出的标准化数据。"""

    provider: Literal["github", "local"] = Field(description="来源提供方")
    repository: str = Field(description="仓库全名或路径")
    title: str = Field(description="PR 标题")
    description: str = Field(default="", description="PR 描述")
    base_sha: str = Field(description="基准提交 SHA")
    head_sha: str = Field(description="目标提交 SHA")
    author: str | None = Field(default=None, description="PR 作者")
    files: list[ChangedFile] = Field(description="变更文件列表")
    raw_diff: str = Field(default="", description="原始 diff 文本")


# ============================================================================
# 审查上下文
# ============================================================================


class ContextPack(BaseModel):
    """审查上下文包 —— 围绕 PR 修改行构建的上下文集合。

    Context Builder 从 diff hunk 出发，收集修改符号、同目录相关代码、
    测试、文档和 Git 历史。单个 Pack 默认字符预算由 Config 控制。
    """

    id: str = Field(description="ContextPack 唯一标识")
    repository: str = Field(description="仓库全名或路径")
    base_sha: str = Field(description="基准提交 SHA")
    head_sha: str = Field(description="目标提交 SHA")
    pr_title: str = Field(default="", description="PR 标题")
    pr_description: str = Field(default="", description="PR 描述")
    files: list[str] = Field(description="包含的文件路径列表")
    diff_hunks: list[DiffHunk] = Field(description="相关 diff hunk")
    enclosing_code: list[CodeEvidence] = Field(
        default_factory=list, description="修改符号的封闭代码"
    )
    related_code: list[CodeEvidence] = Field(
        default_factory=list, description="直接相关代码"
    )
    related_tests: list[CodeEvidence] = Field(
        default_factory=list, description="相关测试代码"
    )
    project_docs: list[TextEvidence] = Field(
        default_factory=list, description="项目文档片段"
    )
    git_history: list[TextEvidence] = Field(
        default_factory=list, description="Git 历史记录"
    )
    static_signals: list[StaticSignal] = Field(
        default_factory=list, description="静态分析信号"
    )
    retrieval_notes: list[str] = Field(
        default_factory=list, description="上下文检索说明"
    )
    truncated: bool = Field(default=False, description="上下文是否被截断")


# ============================================================================
# Finding 与 Verdict
# ============================================================================


class Finding(BaseModel):
    """审查发现 —— Agent 产出的候选缺陷。

    约束：
    - confidence 必须在 0 到 1 之间
    - 至少包含一条代码证据
    - 至少一条证据来自修改文件
    - reasoning_summary 是可公开的结论摘要，不包含隐藏思维链
    """

    id: str = Field(description="Finding 唯一标识")
    producer: Literal["defect", "intent"] = Field(description="生产 Agent 角色")
    category: Literal[
        "static",
        "business_logic",
        "logic",
        "memory",
        "security",
        "architecture",
        "reliability",
    ] = Field(description="缺陷类别")
    severity: Literal["critical", "high", "medium", "low"] = Field(
        description="严重程度"
    )
    confidence: float = Field(ge=0, le=1, description="置信度 0-1")
    file: str = Field(description="目标文件路径")
    line_start: int = Field(ge=1, description="起始行号")
    line_end: int = Field(ge=1, description="结束行号")
    title: str = Field(description="缺陷标题")
    description: str = Field(description="缺陷描述")
    trigger_condition: str = Field(description="触发条件")
    impact: str = Field(description="实际影响")
    reasoning_summary: str = Field(description="可公开的推理摘要")
    suggestion: str | None = Field(default=None, description="修复建议")
    evidence: list[CodeEvidence] = Field(description="代码证据列表")

    @model_validator(mode="after")
    def _validate_evidence_not_empty(self) -> "Finding":
        """Finding 至少需要一条代码证据。"""
        if len(self.evidence) == 0:
            raise ValueError("Finding 至少需要一条代码证据")
        return self

    @model_validator(mode="after")
    def _validate_line_order(self) -> "Finding":
        """结束行号不能小于起始行号。"""
        if self.line_end < self.line_start:
            raise ValueError(
                f"line_end ({self.line_end}) 不能小于 line_start ({self.line_start})"
            )
        return self


class Verdict(BaseModel):
    """Verifier 判决 —— 对候选 Finding 的验证结论。"""

    finding_id: str = Field(description="关联的 Finding ID")
    accepted: bool = Field(description="是否接受")
    verdict: Literal[
        "confirmed",
        "likely",
        "insufficient_evidence",
        "false_positive",
        "duplicate",
        "not_introduced_by_pr",
        "not_on_changed_line",
        "style_only",
    ] = Field(description="判决类型")
    confidence: float = Field(ge=0, le=1, description="Verifier 置信度")
    severity: Literal["critical", "high", "medium", "low"] | None = Field(
        default=None, description="修正后的严重度"
    )
    reason: str = Field(description="判决理由（中文）")
    final_finding: Finding | None = Field(
        default=None, description="修正后的最终 Finding"
    )


# ============================================================================
# 审查结果
# ============================================================================


class ReviewResult(BaseModel):
    """审查结果 —— Orchestrator 产出的最终报告数据。"""

    run_id: str = Field(description="运行 ID")
    status: Literal["completed", "partial", "failed"] = Field(description="运行状态")
    repository: str = Field(description="仓库全名或路径")
    base_sha: str = Field(description="基准提交 SHA")
    head_sha: str = Field(description="目标提交 SHA")
    findings: list[Finding] = Field(description="最终接受的 Finding 列表")
    rejected_count: int = Field(default=0, ge=0, description="被 Verifier 拒绝的候选数")
    coverage: list[str] = Field(default_factory=list, description="覆盖的审查维度")
    warnings: list[str] = Field(default_factory=list, description="运行期间的中文警告")
    started_at: datetime = Field(description="开始时间")
    completed_at: datetime = Field(description="完成时间")
    elapsed_seconds: float = Field(ge=0, description="总耗时（秒）")


# ============================================================================
# Agent Team 通信协议
# ============================================================================

# 消息类型枚举
MessageKind = Literal[
    "review_plan",
    "context_available",
    "static_signal",
    "candidate_finding",
    "handoff_request",
    "handoff_response",
    "verification_request",
    "evidence_response",
    "verdict",
    "agent_snapshot",
    "agent_completed",
    "agent_failed",
    "budget_warning",
    "cancel",
]


class ReviewPlan(BaseModel):
    """TeamLead 产出的审查计划。

    包含分片策略、风险路由和预算分配。
    """

    run_id: str = Field(description="关联运行 ID")
    shards: list["ShardDefinition"] = Field(
        default_factory=list, description="语义分片定义"
    )
    risk_tags: list[str] = Field(
        default_factory=list,
        description="风险标签，如 security, logic, architecture",
    )
    roles_to_launch: list[Literal["defect", "intent"]] = Field(
        description="需要启动的专家角色"
    )
    estimated_findings: int = Field(default=0, ge=0, description="预估发现数量")
    notes: list[str] = Field(default_factory=list, description="计划备注")


class ShardDefinition(BaseModel):
    """语义分片 —— ReviewPlan 中的单个分片定义。"""

    id: str = Field(description="分片 ID")
    files: list[str] = Field(description="包含的文件路径")
    context_pack_id: str = Field(description="关联的 ContextPack ID")
    assigned_roles: list[Literal["defect", "intent"]] = Field(
        description="分配到该分片的角色"
    )


class HandoffRequest(BaseModel):
    """跨领域移交请求 —— 专家 Agent 之间的结构化移交。"""

    source_agent: str = Field(description="发起移交的 Agent 名称")
    target_agent: Literal["defect", "intent"] = Field(description="目标 Agent 角色")
    hypothesis: str = Field(description="移交的假设")
    file: str = Field(description="相关文件")
    lines: list[int] = Field(description="相关行号")
    requested_check: str = Field(description="请求的检查内容")
    evidence: list[CodeEvidence] = Field(description="附带的代码证据")


class VerificationRequest(BaseModel):
    """Verifier 补证请求 —— Verifier 向专家请求补充证据。"""

    finding_id: str = Field(description="关联 Finding ID")
    target_agent: Literal["defect", "intent"] = Field(description="目标专家角色")
    question: str = Field(description="需要专家回答的问题")
    required_evidence: list[str] = Field(description="需要的证据类型列表")
    deadline_seconds: int = Field(default=30, ge=1, le=60, description="补证截止秒数")


class EvidenceResponse(BaseModel):
    """证据响应 —— 专家对 Verifier 补证请求的回答。"""

    finding_id: str = Field(description="关联 Finding ID")
    conclusion: Literal["supported", "withdrawn", "uncertain"] = Field(
        description="证据支持的结论"
    )
    evidence: list[CodeEvidence] = Field(description="补充的代码证据")
    summary: str = Field(description="中文摘要")


class AgentSnapshot(BaseModel):
    """Agent 状态快照 —— Agent 在收到预算警告或完成时保存当前状态。"""

    agent_id: str = Field(description="Agent 唯一标识")
    role: str = Field(description="Agent 角色")
    status: Literal["running", "completed", "failed", "cancelled"] = Field(
        description="Agent 状态"
    )
    findings_count: int = Field(default=0, ge=0, description="已产生的候选数")
    tool_calls_count: int = Field(default=0, ge=0, description="已完成的工具调用数")
    completed_shards: list[str] = Field(default_factory=list, description="已完成的分片")
    pending_shards: list[str] = Field(default_factory=list, description="未完成的分片")
    warnings: list[str] = Field(default_factory=list, description="Agent 级别警告")
    saved_at: datetime | None = Field(default=None, description="快照保存时间")


class TeamMessage(BaseModel):
    """统一消息外壳 —— Mailbox 中所有 Agent 间通信的载体。"""

    id: str = Field(description="消息唯一 ID")
    run_id: str = Field(description="运行 ID")
    sequence: int = Field(ge=0, description="单调递增序列号")
    timestamp: datetime = Field(description="消息时间戳")
    sender: str = Field(description="发送方 Agent 名称")
    recipient: str = Field(description="接收方 Agent 名称或广播标识")
    kind: MessageKind = Field(description="消息类型")
    correlation_id: str | None = Field(default=None, description="关联消息 ID")
    expires_at: datetime | None = Field(default=None, description="消息过期时间")
    payload: dict[str, Any] = Field(default_factory=dict, description="消息载荷")


# ============================================================================
# 事件协议 (PipelineEvent)
# ============================================================================

# 事件类型枚举
EventType = Literal[
    "review.started",
    "review.completed",
    "review.failed",
    "stage.started",
    "stage.completed",
    "stage.failed",
    "agent.started",
    "agent.tool",
    "agent.candidate",
    "agent.completed",
    "agent.failed",
    "verifier.started",
    "verifier.accepted",
    "verifier.rejected",
    "verifier.completed",
    "report.generated",
]


class PipelineEvent(BaseModel):
    """管道事件 —— 前端和后端之间的统一事件协议。

    SSE 和 Replay 输出相同格式的事件，前端不需要维护两套逻辑。
    """

    id: str = Field(description="事件唯一 ID")
    run_id: str = Field(description="运行 ID")
    sequence: int = Field(ge=0, description="单调递增序列号")
    timestamp: datetime = Field(description="事件时间戳")
    type: EventType = Field(description="事件类型")
    data: dict[str, Any] = Field(default_factory=dict, description="事件数据")


# ============================================================================
# API 错误响应
# ============================================================================


class ErrorResponse(BaseModel):
    """统一 API 错误响应。"""

    error_code: str = Field(
        description="错误码：PR_NOT_FOUND | TIMEOUT | VALIDATION_ERROR | REPLAY_NOT_FOUND | INTERNAL_ERROR"
    )
    detail: str = Field(description="中文可读描述")
    run_id: str | None = Field(default=None, description="关联运行 ID")
