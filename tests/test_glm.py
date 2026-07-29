"""GLM 兼容模型构建测试。"""

from pydantic import SecretStr

from reviewcrew.config import Config
import reviewcrew.llm.glm as glm
from reviewcrew.llm.glm import build_glm_model, build_smoke_config


def test_build_glm_model_uses_config_without_exposing_api_key() -> None:
    """模型名称和地址来自配置，且对象展示不会泄露密钥。"""

    config = Config(
        llm_model="glm-5.2",
        llm_base_url="https://glm.example/v1",
        llm_api_key=SecretStr("secret-value-must-not-appear"),
    )

    model = build_glm_model(config)

    assert model.model_name == "glm-5.2"
    assert "glm.example" in repr(model.provider)
    assert "secret-value-must-not-appear" not in repr(model)


def test_build_glm_model_propagates_configured_temperature_and_timeout() -> None:
    """模型设置必须使用配置的温度和超时。"""

    model = build_glm_model(
        Config(
            llm_model="glm-5.2",
            llm_base_url="https://glm.example/v1",
            llm_temperature=0.35,
            llm_timeout_seconds=45,
        )
    )

    assert model.settings == {"temperature": 0.35, "timeout": 45}


def test_smoke_config_uses_glm_defaults_when_only_key_is_set() -> None:
    """仅设置 GLM_API_KEY 时 smoke 使用 GLM 默认模型和端点。"""

    config = build_smoke_config({"GLM_API_KEY": "test-key"})

    assert config.llm_model == "glm-5.2"
    assert config.llm_base_url == "https://open.bigmodel.cn/api/paas/v4/"


async def test_smoke_uses_glm_config_for_the_model_call(monkeypatch) -> None:
    """Smoke 将仅提供的 GLM 密钥发送到 GLM 默认模型和端点。"""

    captured: list[Config] = []

    async def fake_run(config: Config) -> object:
        captured.append(config)
        return glm._SmokeResponse(status="ok")

    monkeypatch.setenv("GLM_API_KEY", "test-key")
    monkeypatch.setattr(glm, "_run_smoke_agent", fake_run)

    assert await glm._smoke() == 0
    assert captured[0].llm_model == "glm-5.2"
    assert captured[0].llm_base_url == "https://open.bigmodel.cn/api/paas/v4/"
