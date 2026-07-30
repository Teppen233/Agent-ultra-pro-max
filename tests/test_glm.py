from __future__ import annotations

import httpx
import pytest
from pydantic_ai import UnexpectedModelBehavior

from reviewcrew.config import Config
from reviewcrew.llm.glm import (
    RetryTransport,
    build_glm_model,
    build_model_settings,
    unlimited_usage,
    retry_unexpected_model_behavior,
)


def test_build_model_uses_glm_name() -> None:
    config = Config(glm_api_key="test-key", glm_model="glm-4-plus")
    model = build_glm_model(config=config)
    model_name = getattr(model, "model_name", getattr(model, "model", ""))
    assert "glm" in str(model_name).lower()


def test_model_settings_disable_incompatible_thinking_mode() -> None:
    settings = build_model_settings(0.2)
    assert settings["thinking"] is False
    assert settings["extra_body"] == {"thinking": {"type": "disabled"}}


def test_model_usage_has_no_request_or_token_limits() -> None:
    limits = unlimited_usage()
    assert limits.request_limit is None
    assert limits.tool_calls_limit is None
    assert limits.input_tokens_limit is None
    assert limits.output_tokens_limit is None
    assert limits.total_tokens_limit is None


@pytest.mark.asyncio
async def test_retry_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429 if attempts == 1 else 200, request=request)

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("reviewcrew.llm.glm.asyncio.sleep", no_sleep)
    transport = RetryTransport(httpx.MockTransport(handler), retries=1, backoff=0)
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get("https://example.test")
    assert response.status_code == 200
    assert attempts == 2


async def test_retry_unexpected_model_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    retries: list[tuple[int, int]] = []

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise UnexpectedModelBehavior("invalid structured response")
        return "ok"

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("reviewcrew.llm.glm.asyncio.sleep", no_sleep)
    result = await retry_unexpected_model_behavior(
        operation,
        retries=3,
        on_retry=lambda current, maximum, _: retries.append((current, maximum)),
    )

    assert result == "ok"
    assert attempts == 3
    assert retries == [(1, 3), (2, 3)]
