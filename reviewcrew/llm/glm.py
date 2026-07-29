"""GLM 的 OpenAI 兼容模型适配。"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from reviewcrew.config import Config


logger = logging.getLogger(__name__)
_MIN_STABLE_TEMPERATURE = 0.0


def build_glm_model(config: Config) -> Model:
    """使用配置创建 OpenAI 兼容的 GLM 模型，且不记录密钥。"""

    if config.llm_provider != "openai-compatible":
        raise ValueError("GLM 仅支持 openai-compatible Provider")
    api_key = config.llm_api_key.get_secret_value() if config.llm_api_key is not None else None
    provider = OpenAIProvider(base_url=config.llm_base_url, api_key=api_key)
    logger.info("已创建 GLM 兼容模型：%s", config.llm_model)
    return OpenAIChatModel(
        config.llm_model,
        provider=provider,
        settings={"temperature": _MIN_STABLE_TEMPERATURE},
    )


class _SmokeResponse(BaseModel):
    """Smoke 命令所需的固定结构化响应。"""

    status: Literal["ok"]


async def _smoke() -> int:
    """验证已配置的 GLM 能返回固定 Pydantic 对象。"""

    api_key = os.environ.get("GLM_API_KEY")
    if not api_key:
        print("未设置 GLM_API_KEY，无法执行 GLM 连通性检查。", file=sys.stderr)
        return 1
    config = Config(llm_api_key=api_key)
    agent = Agent(build_glm_model(config), output_type=_SmokeResponse, retries=config.llm_max_retries)
    try:
        result = await agent.run("仅返回 status 为 ok 的对象。")
    except Exception as error:
        print(f"GLM 连通性检查失败：{type(error).__name__}", file=sys.stderr)
        return 1
    if not isinstance(result.output, _SmokeResponse) or result.output.status != "ok":
        print("GLM 连通性检查失败：未返回预期的结构化对象。", file=sys.stderr)
        return 1
    print("GLM 连通性检查通过。")
    return 0


def main() -> int:
    """执行显式 GLM smoke 命令。"""

    if "--smoke" not in sys.argv[1:]:
        print("请使用 --smoke 执行 GLM 连通性检查。", file=sys.stderr)
        return 2
    return asyncio.run(_smoke())


if __name__ == "__main__":
    raise SystemExit(main())
