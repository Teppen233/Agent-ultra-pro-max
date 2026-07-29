"""配置模块测试 —— 验证环境变量读取、校验和默认值。"""

import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def _reset_config_singleton():
    """每个测试前重置 Config 单例，确保测试隔离。"""
    from reviewcrew.config import Config
    Config.reset_singleton()


def test_config_rejects_invalid_global_timeout(monkeypatch):
    """全局超时为零或负数时应拒绝。"""
    monkeypatch.setenv("REVIEWCREW_GLOBAL_TIMEOUT_SECONDS", "0")
    from reviewcrew.config import Config

    with pytest.raises(ValidationError):
        Config.from_env()


def test_config_defaults_to_600_seconds(monkeypatch):
    """不设置全局超时时默认为 600 秒。"""
    # 清除可能存在的环境变量
    monkeypatch.delenv("REVIEWCREW_GLOBAL_TIMEOUT_SECONDS", raising=False)
    from reviewcrew.config import Config

    config = Config.from_env()
    assert config.global_timeout_seconds == 600


def test_config_reads_llm_settings(monkeypatch):
    """LLM 配置应从环境变量正确读取。"""
    monkeypatch.setenv("LLM_BASE_URL", "https://test.api.com/v1")
    monkeypatch.setenv("LLM_MODEL_NAME", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "sk-test-123")
    from reviewcrew.config import Config

    config = Config.from_env()
    assert config.llm_base_url == "https://test.api.com/v1"
    assert config.llm_model_name == "test-model"
    assert config.llm_api_key.get_secret_value() == "sk-test-123"


def test_config_llm_api_key_not_in_repr(monkeypatch):
    """API Key 不应出现在 repr 输出中。"""
    monkeypatch.setenv("LLM_API_KEY", "sk-secret-abc")
    from reviewcrew.config import Config

    config = Config.from_env()
    repr_str = repr(config)
    assert "sk-secret-abc" not in repr_str


def test_config_stage_timeouts_have_defaults(monkeypatch):
    """各阶段超时应使用设计规范默认值。"""
    from reviewcrew.config import Config

    config = Config.from_env()
    assert config.pr_load_timeout_seconds == 30
    assert config.context_timeout_seconds == 90
    assert config.expert_timeout_seconds == 300
    assert config.verifier_timeout_seconds == 120
    assert config.report_timeout_seconds == 30
