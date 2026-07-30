"""定义 ReviewCrew 全局唯一的领域模型。"""

from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Any, Literal

from pydantic import BaseModel, Field, PrivateAttr, model_validator


class ReviewRequest(BaseModel):
    """一次审查、回放或本地提交比较请求。"""

    pr_url: str | None = None
    repo_path: str | None = None
    base_ref: str | None = None
    head_ref: str | None = None
    replay_run_id: str | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> "ReviewRequest":
        """确保请求只选择一种完整输入模式。"""

        github_mode = self.pr_url is not None
        replay_mode = self.replay_run_id is not None
        local_fields = (self.repo_path, self.base_ref, self.head_ref)
        local_mode = all(value is not None for value in local_fields)
        partial_local_mode = any(value is not None for value in local_fields) and not local_mode
        if partial_local_mode:
            raise ValueError("本地模式必须同时提供仓库路径、基准引用和目标引用")
        if sum((github_mode, replay_mode, local_mode)) != 1:
            raise ValueError("审查请求必须且只能选择一种输入模式")
        return self


class DiffHunk(BaseModel):
    """统一差异中的一个修改块。"""

    id: str
    file: str
    old_start: int = Field(ge=0)
    old_count: int = Field(ge=0)
    new_start: int = Field(ge=0)
    new_count: int = Field(ge=0)
    changed_lines: list[int] = Field(default_factory=list)
    content: str


class ChangedFile(BaseModel):
    """一次 PR 中的变更文件。"""

    path: str
    old_path: str | None = None
    status: Literal["added", "modified", "deleted", "renamed"]
    additions: int = Field(default=0, ge=0)
    deletions: int = Field(default=0, ge=0)
    hunks: list[DiffHunk] = Field(default_factory=list)


class PRData(BaseModel):
    """经过标准化的 PR 元数据与差异。"""

    provider: Literal["github", "local"]
    repository: str
    title: str
    description: str = ""
    base_sha: str
    head_sha: str
    author: str | None = None
    files: list[ChangedFile] = Field(default_factory=list)
    raw_diff: str


class CodeEvidence(BaseModel):
    """带精确位置的代码证据。"""

    source: str
    file: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    description: str
    content: str
    content_hash: str | None = None

    @model_validator(mode="after")
    def validate_lines(self) -> "CodeEvidence":
        """校验证据行号顺序。"""

        if self.end_line < self.start_line:
            raise ValueError("证据结束行不能小于开始行")
        return self


class TextEvidence(BaseModel):
    """来自项目文档或 Git 历史的文本证据。"""

    source: str
    title: str
    content: str
    reference: str | None = None


class StaticSignal(BaseModel):
    """传统扫描工具产生的待裁决信号。"""

    provider: str
    rule_id: str
    file: str
    line: int = Field(ge=1)
    message: str
    severity: Literal["critical", "high", "medium", "low", "info"]


class ContextPack(BaseModel):
    """围绕一组修改构造的受预算约束上下文。"""

    id: str
    repository: str
    base_sha: str
    head_sha: str
    pr_title: str
    pr_description: str = ""
    files: list[str]
    diff_hunks: list[DiffHunk]
    enclosing_code: list[CodeEvidence] = Field(default_factory=list)
    related_code: list[CodeEvidence] = Field(default_factory=list)
    related_tests: list[CodeEvidence] = Field(default_factory=list)
    project_docs: list[TextEvidence] = Field(default_factory=list)
    git_history: list[TextEvidence] = Field(default_factory=list)
    static_signals: list[StaticSignal] = Field(default_factory=list)
    retrieval_notes: list[str] = Field(default_factory=list)
    truncated: bool = False


FindingCategory = Literal[
    "static",
    "business_logic",
    "logic",
    "memory",
    "security",
    "architecture",
    "reliability",
]
Severity = Literal["critical", "high", "medium", "low"]


class Finding(BaseModel):
    """专家 Agent 发布、等待验证的候选问题。"""

    id: str
    producer: Literal["defect", "intent"]
    category: FindingCategory
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    file: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    title: str
    description: str
    trigger_condition: str
    impact: str
    reasoning_summary: str
    suggestion: str | None = None
    evidence: list[CodeEvidence] = Field(min_length=1)
    created_at: datetime

    @model_validator(mode="after")
    def validate_lines(self) -> "Finding":
        """校验候选问题的行号顺序。"""

        if self.line_end < self.line_start:
            raise ValueError("候选问题结束行不能小于开始行")
        return self


class Verdict(BaseModel):
    """Verifier 对候选问题给出的最终裁决。"""

    finding_id: str
    accepted: bool
    verdict: Literal[
        "confirmed",
        "likely",
        "insufficient_evidence",
        "false_positive",
        "duplicate",
        "not_introduced_by_pr",
        "not_on_changed_line",
        "style_only",
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    severity: Severity | None = None
    reason: str
    final_finding: Finding | None = None


class ReviewResult(BaseModel):
    """一次审查运行的最终结果。"""

    run_id: str
    status: Literal["completed", "partial", "failed"]
    repository: str
    base_sha: str
    head_sha: str
    findings: list[Finding] = Field(default_factory=list)
    rejected_count: int = Field(default=0, ge=0)
    coverage: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime
    elapsed_seconds: float = Field(ge=0.0)


class Budget(BaseModel):
    """跨 Agent 编排共享的时间与模型请求预算。"""

    seconds: int = Field(gt=0)
    max_requests: int = Field(default=8, gt=0)
    requests_used: int = Field(default=0, ge=0)
    _request_lock: Lock = PrivateAttr(default_factory=Lock)

    @property
    def remaining_requests(self) -> int:
        """返回剩余的模型请求数量。"""

        with self._request_lock:
            return self.max_requests - self.requests_used

    @property
    def can_expand_shards(self) -> bool:
        """仅在剩余时间和请求均充足时允许增加新的分片。"""

        return self.seconds >= 60 and self.remaining_requests > 0

    def consume_request(self) -> None:
        """消耗一次模型请求，超限时拒绝执行。"""

        self.reserve_requests(1)

    def reserve_requests(self, maximum: int) -> int:
        """在模型调用前原子预留不超过指定数量的请求额度。"""

        if maximum <= 0:
            raise ValueError("模型请求预留数量必须大于零")
        with self._request_lock:
            available = self.max_requests - self.requests_used
            if available <= 0:
                raise RuntimeError("模型请求数已达到预算上限")
            reserved = min(maximum, available)
            self.requests_used += reserved
            return reserved

    def release_requests(self, count: int) -> None:
        """释放模型调用未实际使用的预留额度。"""

        if count < 0:
            raise ValueError("模型请求释放数量不能小于零")
        with self._request_lock:
            if count > self.requests_used:
                raise RuntimeError("释放的模型请求额度超过已预留数量")
            self.requests_used -= count


class ReviewPlan(BaseModel):
    """TeamLead 为本次 PR 生成的并行审查计划。"""

    summary: str
    risk_tags: list[str] = Field(default_factory=list)
    required_agents: list[Literal["defect", "intent"]] = Field(default_factory=list)
    context_ids: list[str] = Field(default_factory=list)
    shards: dict[str, list[str]] = Field(default_factory=dict)
    budget_seconds: int = Field(gt=0)


ToolActorType = Literal["system", "agent"]
ToolActivityStatus = Literal["started", "completed", "degraded", "failed"]


class ToolActivityData(BaseModel):
    """前端可安全展示的真实工具活动摘要。"""

    actor: str = Field(max_length=120)
    actor_type: ToolActorType
    tool_name: str = Field(max_length=120)
    status: ToolActivityStatus
    target: str = Field(default="", max_length=240)
    summary: str = Field(default="", max_length=500)
    duration_ms: int = Field(default=0, ge=0)
    result_count: int | None = Field(default=None, ge=0)
    context_id: str | None = Field(default=None, max_length=120)
    agent_id: str | None = Field(default=None, max_length=160)


class PlanPublishedData(BaseModel):
    """TeamLead 计划可公开的风险、分片和预算摘要。"""

    risk_tags: list[str] = Field(default_factory=list, max_length=32)
    context_ids: list[str] = Field(default_factory=list, max_length=64)
    shards: dict[str, list[str]] = Field(default_factory=dict)
    budget_seconds: int = Field(gt=0)
    summary: str = Field(max_length=500)


PublicMailboxKind = Literal[
    "candidate_finding",
    "evidence_request",
    "evidence_response",
    "verifier_final",
    "agent_review_completed",
]


class MailboxEventData(BaseModel):
    """前端可展示但不冒充工具调用的 Mailbox 协作摘要。"""

    sender: str = Field(max_length=160)
    recipient: str = Field(max_length=160)
    kind: PublicMailboxKind
    correlation_id: str | None = Field(default=None, max_length=160)
    summary: str = Field(max_length=500)


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
    "agent_review_completed",
    "agent_completed",
    "agent_failed",
    "budget_warning",
    "cancel",
]


class TeamMessage(BaseModel):
    """Agent Team 内部使用的类型化消息外壳。"""

    id: str
    run_id: str
    sequence: int = Field(ge=1)
    timestamp: datetime
    sender: str
    recipient: str
    kind: MessageKind
    correlation_id: str | None = None
    expires_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class HandoffRequest(BaseModel):
    """一个专家向另一专家发送的定向移交。"""

    source_agent: str
    target_agent: Literal["defect", "intent"]
    hypothesis: str
    file: str
    lines: list[int]
    requested_check: str
    evidence: list[CodeEvidence] = Field(default_factory=list)


class HandoffAssessment(BaseModel):
    """专家对定向移交执行复查后可公开的结构化结论。"""

    conclusion: Literal["supported", "unsupported", "insufficient"]
    reason: str = Field(min_length=1)
    evidence: list[CodeEvidence] = Field(default_factory=list)


class VerificationRequest(BaseModel):
    """Verifier 向原专家发出的补证请求。"""

    finding_id: str
    target_agent: Literal["defect", "intent"]
    question: str
    required_evidence: list[str] = Field(default_factory=list)
    deadline_seconds: int = Field(default=30, gt=0, le=120)


class EvidenceResponse(BaseModel):
    """专家针对补证请求返回的结构化响应。"""

    finding_id: str
    conclusion: Literal["supported", "withdrawn", "uncertain"]
    evidence: list[CodeEvidence] = Field(default_factory=list)
    summary: str


class AgentSnapshot(BaseModel):
    """Agent 在超时或收敛前保存的当前成果。"""

    agent_id: str
    findings: list[Finding] = Field(default_factory=list)
    completed_checks: list[str] = Field(default_factory=list)
    pending_checks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
