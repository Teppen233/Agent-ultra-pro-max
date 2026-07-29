"""GLM 兼容模型构建测试。"""

from pydantic import SecretStr

from reviewcrew.config import Config
from reviewcrew.llm.glm import build_glm_model


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
