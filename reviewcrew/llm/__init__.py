"""大语言模型适配层。"""

from typing import Any

__all__ = ["build_glm_model"]


def __getattr__(name: str) -> Any:
    """延迟导入模型构建器，避免模块命令触发重复加载警告。"""

    if name == "build_glm_model":
        from reviewcrew.llm.glm import build_glm_model

        return build_glm_model
    raise AttributeError(name)
