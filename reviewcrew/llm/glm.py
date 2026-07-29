"""GLM 的 OpenAI 兼容模型适配。"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Mapping
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from reviewcrew.config import Config


logger = logging.getLogger(__name__)
_DEFAULT_GLM_MODEL = "glm-5.2"
_DEFAULT_GLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"


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
        settings={"temperature": config.llm_temperature, "timeout": config.llm_timeout_seconds},
    )


class _SmokeResponse(BaseModel):
    """Smoke 命令所需的固定结构化响应。"""

    status: Literal["ok"]


async def _smoke() -> int:
    """验证已配置的 GLM 能返回固定 Pydantic 对象。"""

    try:
        config = build_smoke_config(os.environ)
    except ValueError:
        print("未设置 GLM_API_KEY，无法执行 GLM 连通性检查。", file=sys.stderr)
        return 1
    host = urlparse(config.llm_base_url).netloc
    print(f"正在检查 GLM 模型 {config.llm_model}，目标主机：{host}。")
    try:
        response = await _run_smoke_agent(config)
    except Exception as error:
        print(f"GLM 连通性检查失败：{type(error).__name__}", file=sys.stderr)
        return 1
    if not isinstance(response, _SmokeResponse) or response.status != "ok":
        print("GLM 连通性检查失败：未返回预期的结构化对象。", file=sys.stderr)
        return 1
    print("GLM 连通性检查通过。")
    return 0


def build_smoke_config(environ: Mapping[str, str]) -> Config:
    """从 GLM 专用环境变量构造 smoke 配置，避免落到其他 Provider 默认值。"""

    api_key = environ.get("GLM_API_KEY")
    if not api_key:
        raise ValueError("缺少 GLM_API_KEY")
    return Config(
        llm_api_key=api_key,
        llm_model=environ.get("GLM_MODEL", _DEFAULT_GLM_MODEL),
        llm_base_url=environ.get("GLM_BASE_URL", _DEFAULT_GLM_BASE_URL),
        llm_temperature=float(environ.get("GLM_TEMPERATURE", "0.0")),
        llm_timeout_seconds=float(environ.get("GLM_TIMEOUT_SECONDS", "120")),
        llm_max_retries=int(environ.get("GLM_MAX_RETRIES", "2")),
    )


async def _run_smoke_agent(config: Config) -> _SmokeResponse:
    """执行固定结构化 smoke 请求，便于离线替身验证目标配置。"""

    agent = Agent(build_glm_model(config), output_type=_SmokeResponse, retries=config.llm_max_retries)
    result = await agent.run("仅返回 status 为 ok 的对象。")
    return result.output


def main() -> int:
    """执行显式 GLM smoke 命令。"""

    if "--smoke" not in sys.argv[1:]:
        print("请使用 --smoke 执行 GLM 连通性检查。", file=sys.stderr)
        return 2
    return asyncio.run(_smoke())


if __name__ == "__main__":
    raise SystemExit(main())
