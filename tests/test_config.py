from __future__ import annotations

import pytest

from reviewcrew.config import Config


def test_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("REVIEWCREW_TIMEOUT", "42")
    config = Config.from_env()
    assert config.glm_api_key == "test-key"
    assert config.glm_model == "deepseek-v4-pro"
    assert config.pipeline_timeout_seconds == 42


def test_config_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        Config.from_env()
