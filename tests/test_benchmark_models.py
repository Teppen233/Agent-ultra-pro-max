"""Greptile Benchmark 数据模型与数据集校验测试。"""

from importlib import import_module
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).parents[1]


def models_module():
    """延迟导入待实现模块，使 RED 阶段表现为测试失败而非收集错误。"""

    return import_module("benchmark.models")


def valid_ready_payload() -> dict[str, object]:
    """构造字段完整且明确标记为离线 fixture 的 ready 案例。"""

    return {
        "id": "sentry-offline-01",
        "project": "sentry",
        "title": "离线分页器导入案例",
        "language": "Python",
        "severity": "high",
        "status": "ready",
        "source_kind": "offline_fixture",
        "source_url": "fixture://greptile/sentry-01",
        "upstream_repo": "fixture/getsentry-sentry",
        "fork_repo": "fixture/reviewcrew-sentry",
        "test_pr": "fixture://reviewcrew/sentry/pr/1",
        "source_fix_pr": "fixture://reviewcrew/sentry/source-fix/1",
        "base_sha": "fixture-sentry-base",
        "head_sha": "fixture-sentry-head",
        "introducing_commit": "fixture-sentry-introducing",
        "fixing_commit": "fixture-sentry-fixing",
        "bug_locations": [
            {"file": "src/pagination.py", "start_line": 40, "end_line": 42}
        ],
        "bug_description": "导入了不存在的分页器，模块加载时会失败。",
        "mechanism_keywords": ["不存在的分页器"],
        "impact_keywords": ["模块加载失败"],
        "line_tolerance": 0,
    }


@pytest.mark.parametrize(
    "missing_field",
    [
        "fork_repo",
        "test_pr",
        "source_fix_pr",
        "base_sha",
        "head_sha",
        "introducing_commit",
        "fixing_commit",
        "bug_locations",
        "bug_description",
        "mechanism_keywords",
        "impact_keywords",
    ],
)
def test_ready_case_rejects_missing_auditable_field(missing_field: str) -> None:
    """任何 ready 案例缺少可审计字段都会被拒绝，防止进入真实分母。"""

    models = models_module()
    payload = valid_ready_payload()
    payload[missing_field] = [] if missing_field in {
        "bug_locations",
        "mechanism_keywords",
        "impact_keywords",
    } else None

    with pytest.raises(ValidationError, match="ready 案例缺少必需字段"):
        models.DatasetEntry.model_validate(payload)


def test_public_dataset_is_five_language_needs_review_skeleton() -> None:
    """公开骨架覆盖五仓五语言，但未经原始修复映射核验时不得伪装成 ready。"""

    models = models_module()
    entries = models.load_dataset(ROOT / "benchmark" / "dataset.yaml", ready_only=False)

    assert {(entry.project, entry.language) for entry in entries} == {
        ("sentry", "Python"),
        ("calcom", "TypeScript"),
        ("grafana", "Go"),
        ("keycloak", "Java"),
        ("discourse", "Ruby"),
    }
    assert all(entry.status == "needs_review" for entry in entries)
    assert all(entry.source_kind == "public_case" for entry in entries)
    assert all(entry.introducing_commit is None for entry in entries)
    assert all(entry.fixing_commit is None for entry in entries)
    assert models.load_dataset(ROOT / "benchmark" / "dataset.yaml") == []


def test_offline_fixture_dataset_has_one_ready_case_per_repository() -> None:
    """Fake 数据集提供五个完全离线且可运行的案例，不借用公开仓库身份。"""

    models = models_module()
    entries = models.load_dataset(
        ROOT / "benchmark" / "fixtures" / "fake_dataset.yaml",
        ready_only=True,
    )

    assert len(entries) == 5
    assert len({entry.project for entry in entries}) == 5
    assert all(entry.status == "ready" for entry in entries)
    assert all(entry.source_kind == "offline_fixture" for entry in entries)
    assert all(entry.test_pr.startswith("fixture://") for entry in entries)


def test_public_sentry_records_only_verified_reconstructed_pr_shas() -> None:
    """已公开核验的重建 PR SHA 可记录，但不能因此补造原始修复映射或标记 ready。"""

    models = models_module()
    entries = models.load_dataset(ROOT / "benchmark" / "dataset.yaml", ready_only=False)
    sentry = next(entry for entry in entries if entry.project == "sentry")

    assert sentry.base_sha == "a5d290951def84afdcc4c88d2f1f20023fc36e2a"
    assert sentry.head_sha == "8ab88145113dd23a930e23b9cbbcf8b30e4c0b17"
    assert sentry.source_fix_pr is None
    assert sentry.introducing_commit is None
    assert sentry.fixing_commit is None
    assert sentry.status == "needs_review"


def test_public_dataset_transcribes_one_real_case_library_row_per_repository() -> None:
    """公共骨架记录页面已发布的真实标题、严重度和重建 PR，不用通用占位符。"""

    models = models_module()
    entries = models.load_dataset(ROOT / "benchmark" / "dataset.yaml", ready_only=False)
    actual = {
        entry.project: (entry.title, entry.severity, entry.test_pr, entry.bug_description)
        for entry in entries
    }

    assert actual == {
        "sentry": (
            "Enhanced Pagination Performance for High-Volume Audit Logs",
            "high",
            "https://github.com/ai-code-review-evaluation/sentry-greptile/pull/1",
            "Importing non-existent OptimizedCursorPaginator",
        ),
        "calcom": (
            "Async import of the appStore packages",
            "low",
            "https://github.com/ai-code-review-evaluation/cal.com-greptile/pull/2",
            "Async callbacks in forEach creates unhandled promise rejections",
        ),
        "grafana": (
            "Anonymous: Add configurable device limit",
            "high",
            "https://github.com/ai-code-review-evaluation/grafana-greptile/pull/1",
            "Race condition in CreateOrUpdateDevice method",
        ),
        "keycloak": (
            "Fixing Re-authentication with passkeys",
            "medium",
            "https://github.com/ai-code-review-evaluation/keycloak-greptile/pull/1",
            "ConditionalPasskeysEnabled() called without UserModel parameter",
        ),
        "discourse": (
            "FEATURE: automatically downsize large images",
            "medium",
            "https://github.com/ai-code-review-evaluation/discourse-greptile/pull/1",
            "Method overwriting causing parameter mismatch",
        ),
    }


def test_line_tolerance_is_explicit_and_never_exceeds_ten() -> None:
    """重建 PR 的位置容差必须显式声明，且上限固定为十行。"""

    models = models_module()
    payload = valid_ready_payload()
    payload["line_tolerance"] = 11

    with pytest.raises(ValidationError):
        models.DatasetEntry.model_validate(payload)


def test_public_ready_case_rejects_fixture_provenance_and_non_sha_ids() -> None:
    """公共 ready 案例必须使用 GitHub 来源与真实 SHA 形态，fixture 标识只能留在离线数据。"""

    models = models_module()
    payload = valid_ready_payload()
    payload["source_kind"] = "public_case"

    with pytest.raises(ValidationError, match="公开 ready 案例"):
        models.DatasetEntry.model_validate(payload)


def test_public_ready_case_rejects_fixture_repository_slugs_even_with_valid_urls() -> None:
    """公共来源不能通过伪装成 40 位 SHA 和 GitHub URL 绕过 fixture 仓库身份。"""

    models = models_module()
    payload = valid_ready_payload()
    payload.update(
        {
            "source_kind": "public_case",
            "test_pr": "https://github.com/example/review/pull/1",
            "source_fix_pr": "https://github.com/example/upstream/pull/2",
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "introducing_commit": "c" * 40,
            "fixing_commit": "d" * 40,
        }
    )

    with pytest.raises(ValidationError, match="公开 ready 案例"):
        models.DatasetEntry.model_validate(payload)


def test_public_ready_case_requires_exact_github_pull_request_urls() -> None:
    """仅有 github.com 前缀不足以证明 PR 来源，必须包含 owner/repo/pull/number。"""

    models = models_module()
    payload = valid_ready_payload()
    payload.update(
        {
            "source_kind": "public_case",
            "upstream_repo": "example/upstream",
            "fork_repo": "example/review",
            "test_pr": "https://github.com/not-a-pull-request",
            "source_fix_pr": "https://github.com/example/upstream/pull/2",
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "introducing_commit": "c" * 40,
            "fixing_commit": "d" * 40,
        }
    )

    with pytest.raises(ValidationError, match="公开 ready 案例"):
        models.DatasetEntry.model_validate(payload)
