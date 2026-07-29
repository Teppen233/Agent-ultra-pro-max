"""Greptile Benchmark Runner 与离线报告测试。"""

from importlib import import_module
import json
from pathlib import Path
import socket


ROOT = Path(__file__).parents[1]


def benchmark_modules():
    """延迟导入待实现的模型和 Runner。"""

    return import_module("benchmark.models"), import_module("benchmark.runner")


def load_fake_entries():
    """读取五仓离线 fixture。"""

    models, _ = benchmark_modules()
    return models.load_dataset(
        ROOT / "benchmark" / "fixtures" / "fake_dataset.yaml",
        ready_only=True,
    )


def test_quick_fake_is_offline_and_writes_three_auditable_outputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Fake quick 不触网，每仓至多一例，并输出 JSONL、JSON 和中文 Markdown。"""

    _, runner = benchmark_modules()

    def deny_network(*args, **kwargs):
        raise AssertionError("Fake runner 不得访问网络")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    summary = runner.execute_benchmark(
        load_fake_entries(),
        mode="quick",
        backend=runner.FakeReviewRunner(),
        output_dir=tmp_path,
    )

    assert summary.runner == "fake"
    assert summary.offline is True
    assert summary.selected_cases == 5
    assert summary.real_catch_rate is None
    assert summary.offline_results_excluded_from_real_rate is True
    assert summary.false_positive_count == 3
    assert summary.verifier_accepted_count == 5
    assert summary.verifier_rejected_count == 1

    cases_path = tmp_path / "cases.jsonl"
    summary_path = tmp_path / "summary.json"
    markdown_path = tmp_path / "summary.md"
    assert cases_path.is_file()
    assert summary_path.is_file()
    assert markdown_path.is_file()
    rows = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 5
    assert len({row["project"] for row in rows}) == 5
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["false_positive_count"] == 3
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "runner=fake" in markdown
    assert "offline=true" in markdown
    assert "不计入真实命中率" in markdown
    assert "误报 Finding：3" in markdown


def test_mode_selection_supports_quick_case_and_full() -> None:
    """quick 按仓去重，case 精确选择，full 保留所有 ready 案例。"""

    models, runner = benchmark_modules()
    entries = load_fake_entries()
    duplicate = entries[0].model_copy(update={"id": "sentry-offline-02"})
    all_entries = [*entries, duplicate]

    quick = runner.select_cases(all_entries, mode="quick")
    single = runner.select_cases(all_entries, mode="case", case_id="sentry-offline-02")
    full = runner.select_cases(all_entries, mode="full")

    assert len(quick) == 5
    assert len({entry.project for entry in quick}) == 5
    assert [entry.id for entry in single] == ["sentry-offline-02"]
    assert len(full) == 6
    assert all(isinstance(entry, models.DatasetEntry) for entry in full)


def test_case_mode_rejects_missing_or_unknown_case_id() -> None:
    """case 模式必须提供存在的 ID，避免静默运行错误样本。"""

    _, runner = benchmark_modules()
    entries = load_fake_entries()

    for case_id in (None, "missing-case"):
        try:
            runner.select_cases(entries, mode="case", case_id=case_id)
        except ValueError as error:
            assert "case" in str(error)
        else:
            raise AssertionError("无效 case ID 应被拒绝")


def test_backend_factory_exposes_fake_and_real_interfaces() -> None:
    """调用方可通过稳定名称选择离线 Fake 或注入执行器的 Real 后端。"""

    _, runner = benchmark_modules()
    fake = runner.make_backend("fake")
    real = runner.make_backend("real")

    assert (fake.name, fake.offline) == ("fake", True)
    assert (real.name, real.offline) == ("real", False)


def test_real_runner_uses_test_pr_with_default_orchestrator_adapter() -> None:
    """真实 Runner 无需额外注入 executor，也能把 ready 测试 PR 交给 Orchestrator。"""

    _, runner = benchmark_modules()
    source = load_fake_entries()[0]
    entry = source.model_copy(
        update={
            "source_kind": "public_case",
            "test_pr": "https://github.com/example/reviewcrew-benchmark/pull/1",
        }
    )
    expected = runner.FakeReviewRunner().run(source)

    class RecordingOrchestrator:
        def __init__(self) -> None:
            self.requests = []

        async def review(self, request):
            self.requests.append(request)
            return expected

    orchestrator = RecordingOrchestrator()
    backend = runner.RealReviewRunner(orchestrator_factory=lambda config: orchestrator)

    result = backend.run(entry)

    assert result is expected
    assert orchestrator.requests[0].pr_url == entry.test_pr


def test_runner_records_timeout_without_inflating_real_denominator(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """真实后端超时仍产出报告，但不进入实际完成 ready 案例分母。"""

    _, runner = benchmark_modules()

    class TimeoutBackend:
        name = "real"
        offline = False

        def run(self, entry):
            raise TimeoutError("fixture timeout")

    ticks = iter((10.0, 12.5))
    monkeypatch.setattr(runner, "perf_counter", lambda: next(ticks), raising=False)
    summary = runner.execute_benchmark(
        load_fake_entries()[:1],
        mode="full",
        backend=TimeoutBackend(),
        output_dir=tmp_path,
    )

    assert summary.selected_cases == 1
    assert summary.completed_cases == 0
    assert summary.actually_run_ready_cases == 0
    assert summary.timed_out_cases == 1
    assert summary.elapsed_seconds == 2.5
    assert summary.real_catch_rate is None
    row = json.loads((tmp_path / "cases.jsonl").read_text(encoding="utf-8"))
    assert row["status"] == "failed"
    assert row["timed_out"] is True
    assert row["judge"]["needs_human_review"] is True


def test_runner_records_backend_failure_and_continues_reporting(tmp_path: Path) -> None:
    """非超时执行失败也必须留下可审计记录，而不是中断整次评测。"""

    _, runner = benchmark_modules()

    class FailingBackend:
        name = "real"
        offline = False

        def run(self, entry):
            raise RuntimeError("runner unavailable")

    summary = runner.execute_benchmark(
        load_fake_entries()[:1],
        mode="full",
        backend=FailingBackend(),
        output_dir=tmp_path,
    )

    assert summary.completed_cases == 0
    assert summary.timed_out_cases == 0
    row = json.loads((tmp_path / "cases.jsonl").read_text(encoding="utf-8"))
    assert row["status"] == "failed"
    assert row["timed_out"] is False
    assert "执行失败" in row["judge"]["reason"]


def test_cli_case_flag_selects_one_case_without_explicit_mode(tmp_path: Path) -> None:
    """计划接口 `--case ID` 直接切换到 case 模式，不能被默认 quick 静默忽略。"""

    _, runner = benchmark_modules()
    exit_code = runner.main(
        [
            "--case",
            "sentry-offline-01",
            "--runner",
            "fake",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "case"
    assert payload["selected_cases"] == 1


def test_cli_real_without_executor_returns_nonzero_and_writes_no_success_report(
    tmp_path: Path,
) -> None:
    """未接入真实 ReviewCrew 执行器时应明确失败，不能报告“0 案例完成”。"""

    _, runner = benchmark_modules()
    exit_code = runner.main(
        [
            "--runner",
            "real",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code != 0
    assert not (tmp_path / "summary.json").exists()


def test_cli_unknown_case_returns_nonzero_instead_of_traceback(tmp_path: Path) -> None:
    """未知案例应成为清晰的 CLI 参数错误，不向用户暴露 Python traceback。"""

    _, runner = benchmark_modules()
    exit_code = runner.main(
        [
            "--case",
            "missing-case",
            "--runner",
            "fake",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code != 0
    assert not (tmp_path / "summary.json").exists()


def test_cli_missing_dataset_returns_nonzero_without_traceback(tmp_path: Path) -> None:
    """缺失数据集属于可解释的 CLI 输入错误，不能直接抛 FileNotFoundError。"""

    _, runner = benchmark_modules()
    exit_code = runner.main(
        [
            "--runner",
            "fake",
            "--dataset",
            str(tmp_path / "missing.yaml"),
            "--output-dir",
            str(tmp_path / "output"),
        ]
    )

    assert exit_code != 0
    assert not (tmp_path / "output" / "summary.json").exists()


def test_cli_invalid_yaml_returns_nonzero_without_traceback(tmp_path: Path) -> None:
    """损坏 YAML 也应转成清晰错误码，不泄露内部 traceback。"""

    _, runner = benchmark_modules()
    dataset = tmp_path / "invalid.yaml"
    dataset.write_text("cases: [", encoding="utf-8")

    exit_code = runner.main(
        [
            "--runner",
            "fake",
            "--dataset",
            str(dataset),
            "--output-dir",
            str(tmp_path / "output"),
        ]
    )

    assert exit_code != 0
    assert not (tmp_path / "output" / "summary.json").exists()


def test_cli_fake_quick_uses_offline_fixture_dataset(tmp_path: Path) -> None:
    """公开命令入口在 fake quick 下自动使用离线 fixture 并成功产出报告。"""

    _, runner = benchmark_modules()
    exit_code = runner.main(
        [
            "--mode",
            "quick",
            "--runner",
            "fake",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "cases.jsonl").is_file()
    assert json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))["offline"] is True
