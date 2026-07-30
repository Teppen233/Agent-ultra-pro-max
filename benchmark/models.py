"""Benchmark 数据集、裁决和汇总模型。"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator
import yaml


CaseStatus = Literal["needs_review", "ready", "unavailable"]
SourceKind = Literal["public_case", "offline_fixture"]
BenchmarkSeverity = Literal["critical", "high", "medium", "low"]
RepositoryBenchmarkStatus = Literal[
    "needs_data", "pending", "running", "completed", "partial", "failed"
]


class BugLocation(BaseModel):
    """人工核验的漏洞目标位置。"""

    file: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_range(self) -> "BugLocation":
        """拒绝倒置的目标行区间。"""

        if self.end_line < self.start_line:
            raise ValueError("漏洞目标结束行不能小于开始行")
        return self


class DatasetEntry(BaseModel):
    """一个可审计的 Benchmark 案例或待核验公共骨架。"""

    id: str = Field(min_length=1)
    project: str = Field(min_length=1)
    title: str = Field(min_length=1)
    language: str = Field(min_length=1)
    severity: BenchmarkSeverity | None = None
    status: CaseStatus
    source_kind: SourceKind
    source_url: str = Field(min_length=1)
    upstream_repo: str = Field(min_length=1)
    fork_repo: str | None = None
    test_pr: str | None = None
    source_fix_pr: str | None = None
    base_sha: str | None = None
    head_sha: str | None = None
    introducing_commit: str | None = None
    fixing_commit: str | None = None
    bug_locations: list[BugLocation] = Field(default_factory=list)
    bug_description: str | None = None
    mechanism_keywords: list[str] = Field(default_factory=list)
    impact_keywords: list[str] = Field(default_factory=list)
    line_tolerance: int = Field(default=0, ge=0, le=10)

    @model_validator(mode="after")
    def validate_ready_case(self) -> "DatasetEntry":
        """ready 案例必须具有可追溯、可定位和可语义判定的完整字段。"""

        if self.status != "ready":
            return self
        required = {
            "severity": self.severity,
            "fork_repo": self.fork_repo,
            "test_pr": self.test_pr,
            "source_fix_pr": self.source_fix_pr,
            "base_sha": self.base_sha,
            "head_sha": self.head_sha,
            "introducing_commit": self.introducing_commit,
            "fixing_commit": self.fixing_commit,
            "bug_locations": self.bug_locations,
            "bug_description": self.bug_description,
            "mechanism_keywords": self.mechanism_keywords,
            "impact_keywords": self.impact_keywords,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"ready 案例缺少必需字段：{', '.join(missing)}")
        if self.source_kind == "public_case":
            github_urls = (self.test_pr or "", self.source_fix_pr or "")
            pull_request_pattern = (
                r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*/?"
            )
            commit_ids = (
                self.base_sha or "",
                self.head_sha or "",
                self.introducing_commit or "",
                self.fixing_commit or "",
            )
            repositories = (self.upstream_repo, self.fork_repo or "")
            valid_repositories = all(
                re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
                and not repository.startswith("fixture/")
                for repository in repositories
            )
            if (
                not all(re.fullmatch(pull_request_pattern, url) for url in github_urls)
                or not all(re.fullmatch(r"[0-9a-f]{40}", commit_id) for commit_id in commit_ids)
                or not valid_repositories
            ):
                raise ValueError("公开 ready 案例必须使用 GitHub 来源、真实仓库格式与 40 位十六进制提交 SHA")
        return self


class JudgeResult(BaseModel):
    """三层 Judge 对单个案例的最终判定。"""

    caught: bool
    matched_finding_id: str | None = None
    location_match: bool = False
    semantic_match: bool = False
    used_line_tolerance: int | None = None
    needs_human_review: bool = False
    reason: str
    false_positive_count: int = Field(ge=0)
    verifier_accepted_count: int = Field(ge=0)
    verifier_rejected_count: int = Field(ge=0)


class CaseReport(BaseModel):
    """Runner 持久化的一条案例执行记录。"""

    case_id: str
    project: str
    language: str
    status: Literal["completed", "partial", "failed"]
    elapsed_seconds: float = Field(ge=0.0)
    timed_out: bool = False
    run_id: str | None = None
    judge: JudgeResult


class RepositoryBenchmarkTarget(BaseModel):
    """五仓评测矩阵中一个固定、可展示的仓库目标。"""

    repository: str = Field(min_length=1)
    language: str = Field(min_length=1)


FIVE_REPOSITORIES: tuple[RepositoryBenchmarkTarget, ...] = (
    RepositoryBenchmarkTarget(repository="sentry", language="Python"),
    RepositoryBenchmarkTarget(repository="calcom", language="TypeScript"),
    RepositoryBenchmarkTarget(repository="grafana", language="Go"),
    RepositoryBenchmarkTarget(repository="keycloak", language="Java"),
    RepositoryBenchmarkTarget(repository="discourse", language="Ruby"),
)


class RepositoryBenchmarkSummary(BaseModel):
    """一个仓库的可持久化 Benchmark 汇总，不把离线结果伪装成真实成绩。"""

    repository: str = Field(min_length=1)
    language: str = Field(min_length=1)
    total_cases: int = Field(ge=0)
    verified_cases: int = Field(ge=0)
    executed_cases: int = Field(ge=0)
    target_caught: int = Field(ge=0)
    other_findings: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0.0)
    status: RepositoryBenchmarkStatus
    latest_run_id: str | None = None
    catch_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    observed_offline_catch_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    cases: list[CaseReport] = Field(default_factory=list)


class BenchmarkSummary(BaseModel):
    """一次 Benchmark 运行的可机器读取汇总。"""

    mode: Literal["quick", "case", "full"]
    runner: Literal["fake", "real"]
    offline: bool
    selected_cases: int = Field(ge=0)
    completed_cases: int = Field(ge=0)
    actually_run_ready_cases: int = Field(ge=0)
    caught_cases: int = Field(ge=0)
    real_catch_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    observed_offline_catch_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    offline_results_excluded_from_real_rate: bool
    false_positive_count: int = Field(ge=0)
    verifier_accepted_count: int = Field(ge=0)
    verifier_rejected_count: int = Field(ge=0)
    needs_human_review_cases: int = Field(ge=0)
    timed_out_cases: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0.0)
    repositories: list[RepositoryBenchmarkSummary] = Field(default_factory=list)


def load_dataset(path: Path, ready_only: bool = True) -> list[DatasetEntry]:
    """从 YAML 读取案例，并默认只返回通过完整校验的 ready 案例。"""

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw_entries = payload.get("cases", []) if isinstance(payload, dict) else payload
    if not isinstance(raw_entries, list):
        raise ValueError("Benchmark 数据集必须是案例列表或包含 cases 列表")
    entries = [DatasetEntry.model_validate(item) for item in raw_entries]
    if ready_only:
        return [entry for entry in entries if entry.status == "ready"]
    return entries
