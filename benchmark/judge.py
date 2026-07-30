from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from reviewcrew.llm.glm import build_glm_model, build_model_settings
from reviewcrew.models import Category, Finding


class BugLocation(BaseModel):
    path: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)


class DatasetEntry(BaseModel):
    repo: str
    fork_url: str
    pr_url: str
    base_sha: str
    head_sha: str
    bug_desc: str
    bug_files: list[BugLocation]
    category: Category


class JudgeResult(BaseModel):
    hit: bool
    matched_finding: Finding | None = None
    reason: Literal["line_overlap", "semantic_match", "miss"]


SemanticMatcher = Callable[[Finding, DatasetEntry], bool]


class SemanticDecision(BaseModel):
    match: bool
    reason: str


def build_llm_semantic_matcher() -> SemanticMatcher:
    agent = Agent(
        build_glm_model(),
        output_type=SemanticDecision,
        system_prompt=(
            "Decide whether a code-review finding describes the same root defect as the "
            "benchmark expectation. Require a concrete shared failure mode; do not match on "
            "category or vocabulary alone."
        ),
        model_settings=build_model_settings(0.0),
    )

    def match(finding: Finding, entry: DatasetEntry) -> bool:
        payload = {
            "expected_bug": entry.bug_desc,
            "finding": {
                "title": finding.title,
                "reasoning": finding.reasoning,
                "trigger_path": finding.trigger_path,
                "file": finding.file,
            },
        }
        decision = agent.run_sync(json.dumps(payload, ensure_ascii=True)).output
        return decision.match

    return match


def load_dataset(path: Path) -> list[DatasetEntry]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(raw, list):
        raise ValueError("dataset root must be a list")
    return [DatasetEntry.model_validate(item) for item in raw]


def _overlaps(finding: Finding, location: BugLocation, tolerance: int) -> bool:
    if finding.file.removeprefix("./") != location.path.removeprefix("./"):
        return False
    return (
        finding.line_start <= location.line_end + tolerance
        and finding.line_end >= location.line_start - tolerance
    )


def judge(
    findings: list[Finding],
    entry: DatasetEntry,
    semantic_matcher: SemanticMatcher | None = None,
    line_tolerance: int = 10,
) -> JudgeResult:
    for finding in findings:
        if any(_overlaps(finding, location, line_tolerance) for location in entry.bug_files):
            return JudgeResult(hit=True, matched_finding=finding, reason="line_overlap")

    if semantic_matcher is not None:
        for finding in findings:
            if semantic_matcher(finding, entry):
                return JudgeResult(hit=True, matched_finding=finding, reason="semantic_match")

    return JudgeResult(hit=False, reason="miss")
