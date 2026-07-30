from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Category = Literal["logic", "security", "memory", "architecture", "static"]
Severity = Literal["critical", "high", "medium", "low"]
AgentName = Literal["coordinator", "defect", "intent", "verifier"]
WorkflowKind = Literal[
    "input", "coordinator", "agent_task", "tool", "finding", "verifier", "report"
]
WorkflowNodeStatus = Literal[
    "queued", "running", "waiting", "completed", "failed", "cancelled"
]
WorkflowRelation = Literal[
    "dispatch",
    "depends_on",
    "tool_call",
    "evidence",
    "handoff",
    "candidate",
    "challenge",
    "result",
]


class Hunk(BaseModel):
    old_start: int = Field(ge=0)
    old_count: int = Field(ge=0)
    new_start: int = Field(ge=0)
    new_count: int = Field(ge=0)
    lines: list[str]


class FileDiff(BaseModel):
    path: str
    change_type: Literal["add", "modify", "delete", "rename"]
    old_path: str | None = None
    hunks: list[Hunk]


class Signal(BaseModel):
    provider: str
    rule_id: str
    file: str
    line: int = Field(ge=1)
    message: str
    severity: Literal["error", "warning", "info"]


class Finding(BaseModel):
    id: str = Field(default="")
    category: Category
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    file: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    title: str = Field(max_length=120)
    reasoning: str
    trigger_path: str
    suggestion: str
    verdict: Literal["keep", "reject"] | None = None
    verdict_reason: str | None = None
    confidence_adjusted: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_line_range(self) -> Finding:
        if self.line_end < self.line_start:
            raise ValueError("line_end must be greater than or equal to line_start")
        if not self.id:
            identity = f"{self.file}:{self.line_start}:{self.line_end}:{self.title}"
            self.id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return self


class Verdict(BaseModel):
    finding_id: str
    verdict: Literal["keep", "reject"]
    reason: str
    confidence_adjusted: float = Field(ge=0.0, le=1.0)


class ContextPack(BaseModel):
    pack_id: str
    diff_hunks: list[FileDiff]
    enclosing_code: dict[str, str] = Field(default_factory=dict)
    callers: dict[str, list[str]] = Field(default_factory=dict)
    callees: dict[str, list[str]] = Field(default_factory=dict)
    arch_summary: str = Field(default="", max_length=8192)
    bug_patterns: str = Field(default="", max_length=4096)
    intent: str = ""
    static_signals: list[Signal] = Field(default_factory=list)


class WorkflowNode(BaseModel):
    id: str
    kind: WorkflowKind
    label: str
    status: WorkflowNodeStatus
    agent: AgentName | None = None
    detail: str | None = None
    task_id: str | None = None


class WorkflowEdge(BaseModel):
    id: str
    source: str
    target: str
    relation: WorkflowRelation


class PipelineEvent(BaseModel):
    timestamp: float
    type: Literal[
        "run",
        "stage",
        "workflow_node",
        "workflow_edge",
        "agent",
        "thought",
        "tool",
        "snapshot",
        "finding",
        "verdict",
        "report",
    ]
    stage: Literal["preprocess", "context", "review", "verify", "report"] | None = None
    status: Literal["start", "done", "error"] | None = None
    elapsed: float | None = None
    agent: AgentName | None = None
    agent_status: Literal["running", "done", "error"] | None = None
    task_id: str | None = None
    text: str | None = None
    tool: str | None = None
    args: dict[str, object] | None = None
    result: str | None = None
    snapshot_findings: list[Finding] | None = None
    finding: Finding | None = None
    verdict: Verdict | None = None
    markdown: str | None = None
    findings: list[Finding] | None = None
    workflow_node: WorkflowNode | None = None
    workflow_edge: WorkflowEdge | None = None
