from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
import os
from typing import TypeVar

import httpx
from pydantic_ai import UnexpectedModelBehavior
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from reviewcrew.config import Config

RetryResult = TypeVar("RetryResult")


class RetryTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        retries: int = 3,
        backoff: float = 0.5,
    ) -> None:
        self._transport = transport or httpx.AsyncHTTPTransport()
        self.retries = retries
        self.backoff = backoff

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        for attempt in range(self.retries + 1):
            response = await self._transport.handle_async_request(request)
            if response.status_code != 429 and response.status_code < 500:
                return response
            if attempt == self.retries:
                return response
            await response.aclose()
            await asyncio.sleep(self.backoff * (2**attempt))
        raise RuntimeError("retry loop exhausted")

    async def aclose(self) -> None:
        await self._transport.aclose()


def build_http_client(config: Config) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(120.0),
        transport=RetryTransport(retries=3, backoff=0.5),
    )


def build_glm_model(
    model: str | None = None,
    temperature: float | None = None,
    config: Config | None = None,
) -> OpenAIChatModel:
    """Build a pydantic-ai model backed by GLM's OpenAI-compatible endpoint."""
    resolved = config or Config.from_env()
    model_name = model or resolved.glm_model
    _ = resolved.temperature if temperature is None else temperature
    client = build_http_client(resolved)

    provider = OpenAIProvider(
        base_url=resolved.glm_base_url,
        api_key=resolved.glm_api_key,
        http_client=client,
    )
    return OpenAIChatModel(model_name, provider=provider)


def build_model_settings(temperature: float) -> OpenAIChatModelSettings:
    return OpenAIChatModelSettings(
        temperature=temperature,
        thinking=False,
        extra_body={"thinking": {"type": "disabled"}},
    )


def unlimited_usage() -> UsageLimits:
    return UsageLimits(request_limit=None)


async def retry_unexpected_model_behavior(
    operation: Callable[[], Awaitable[RetryResult]],
    *,
    retries: int | None = None,
    on_retry: Callable[[int, int, UnexpectedModelBehavior], None] | None = None,
) -> RetryResult:
    max_retries = retries if retries is not None else max(
        0, int(os.getenv("REVIEWCREW_MODEL_RETRIES", "3"))
    )
    for attempt in range(max_retries + 1):
        try:
            return await operation()
        except UnexpectedModelBehavior as error:
            if attempt >= max_retries:
                raise
            retry_number = attempt + 1
            if on_retry is not None:
                on_retry(retry_number, max_retries, error)
            await asyncio.sleep(min(4.0, float(2**attempt)))
    raise RuntimeError("unexpected model retry loop exhausted")


async def _iter_once(value: str) -> AsyncIterator[str]:
    yield value


if __name__ == "__main__":
    from pydantic_ai import Agent

    async def smoke_test() -> None:
        agent = Agent(build_glm_model())
        result = await agent.run("Say 'Hello ReviewCrew'")
        print(result.output)

    asyncio.run(smoke_test())
