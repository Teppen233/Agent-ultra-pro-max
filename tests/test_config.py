"""配置模型测试。"""

import pytest
from pydantic import ValidationError

from reviewcrew.config import Config


def test_config_rejects_invalid_global_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """全局超时必须是正整数。"""

    monkeypatch.setenv("REVIEWCREW_GLOBAL_TIMEOUT_SECONDS", "0")

    with pytest.raises(ValidationError):
        Config.from_env()


def test_empty_github_token_is_treated_as_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    """空白 GitHub Token 必须按未配置处理，避免发送无效授权头。"""

    monkeypatch.setenv("REVIEWCREW_GITHUB_TOKEN", "")

    assert Config.from_env().github_token_value() is None


def test_config_defaults_to_eight_concurrent_workers() -> None:
    """未设置环境变量时应启用八个并发工作槽。"""

    assert Config(_env_file=None).max_concurrency == 8


def test_config_exposes_bounded_expert_collaboration_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """专家发布候选后只等待可配置的短协作窗口，不能耗尽整个审查阶段。"""

    monkeypatch.setenv("REVIEWCREW_LLM_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("REVIEWCREW_COLLABORATION_WINDOW_SECONDS", "12.5")

    config = Config.from_env()

    assert config.collaboration_window_seconds == 12.5


def test_config_rejects_collaboration_window_shorter_than_model_timeout() -> None:
    """协作窗口必须覆盖首次 Verifier 模型调用，避免补证请求到达时专家已退出。"""

    with pytest.raises(ValidationError, match="协作窗口"):
        Config(llm_timeout_seconds=20, collaboration_window_seconds=10)


def test_role_model_falls_back_to_global_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """角色未单独配置模型时应回退到全局模型。"""

    monkeypatch.setenv("REVIEWCREW_LLM_MODEL", "deepseek-v4-pro")
    monkeypatch.delenv("REVIEWCREW_DEFECT_MODEL", raising=False)

    config = Config.from_env()

    assert config.model_for("defect") == "deepseek-v4-pro"
