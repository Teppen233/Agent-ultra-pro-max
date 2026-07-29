"""LLM 模型构建 —— 通过 OpenAI 兼容端点接入模型。

默认使用智谱 GLM 系列，可通过 LLM_MODEL_NAME 环境变量替换。
提供 smoke 测试命令验证模型连通性。
"""

from __future__ import annotations

import asyncio
import os
import sys

from ..config import Config


def build_model(config: Config):
    """根据配置构建 Pydantic AI 模型实例。

    通过 OpenAI 兼容 Provider 接入，temperature 使用模型支持的最低稳定值。

    Args:
        config: 全局配置

    Returns:
        Pydantic AI Model 实例

    Raises:
        ValueError: API Key 未配置
    """
    api_key = config.llm_api_key.get_secret_value()
    if not api_key:
        raise ValueError(
            "LLM_API_KEY 环境变量未设置。"
            "请复制 .env.example 为 .env 并填入 API Key。"
        )

    try:
        from pydantic_ai.models.openai import OpenAIModel

        return OpenAIModel(
            model_name=config.llm_model_name,
            base_url=config.llm_base_url,
            api_key=api_key,
        )
    except ImportError:
        raise ImportError(
            "pydantic-ai 未安装，请运行: pip install pydantic-ai"
        )


def build_fake_model():
    """构建 Fake/Test Model，用于离线测试。

    返回 Pydantic AI TestModel，不依赖网络或 API Key。
    """
    from pydantic_ai.models.test import TestModel

    return TestModel()


async def _smoke_test(config: Config) -> bool:
    """执行一次最小模型调用，验证连通性。

    Returns:
        True 表示调用成功
    """
    from pydantic_ai import Agent

    agent = Agent(
        model=build_model(config),
        system_prompt="你是一个代码审查助手。只回答是或否。",
    )

    result = await agent.run("今天的天气好吗？请只回答'是'。")
    return result is not None


def run_smoke() -> None:
    """CLI smoke 命令入口。"""
    config = Config.from_env()
    api_key = config.llm_api_key.get_secret_value()

    if not api_key:
        print("错误: LLM_API_KEY 环境变量未设置。")
        print("请复制 .env.example 为 .env 并填入 API Key 后重试。")
        sys.exit(1)

    print(f"模型: {config.llm_model_name}")
    print(f"端点: {config.llm_base_url}")
    print("正在测试连通性...")

    try:
        success = asyncio.run(_smoke_test(config))
        if success:
            print("✓ 模型调用成功！")
        else:
            print("✗ 模型调用返回空结果。")
            sys.exit(2)
    except Exception as e:
        print(f"✗ 模型调用失败: {e}")
        sys.exit(2)


if __name__ == "__main__":
    run_smoke()
