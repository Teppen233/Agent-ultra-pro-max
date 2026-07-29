"""配置模型测试。"""

import pytest
from pydantic import ValidationError

from reviewcrew.config import Config


def test_config_rejects_invalid_global_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """全局超时必须是正整数。"""

    monkeypatch.setenv("REVIEWCREW_GLOBAL_TIMEOUT_SECONDS", "0")

    with pytest.raises(ValidationError):
        Config.from_env()


def test_role_model_falls_back_to_global_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """角色未单独配置模型时应回退到全局模型。"""

    monkeypatch.setenv("REVIEWCREW_LLM_MODEL", "deepseek-v4-pro")
    monkeypatch.delenv("REVIEWCREW_DEFECT_MODEL", raising=False)

    config = Config.from_env()

    assert config.model_for("defect") == "deepseek-v4-pro"

