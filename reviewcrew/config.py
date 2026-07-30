from __future__ import annotations

import os

from pydantic import BaseModel, Field


class Config(BaseModel):
    glm_api_key: str
    glm_model: str = "deepseek-v4-pro"
    glm_base_url: str = "https://api.ai-native-x.site/v1"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_concurrent_agents: int = Field(default=4, ge=1)
    pipeline_timeout_seconds: int = Field(default=600, ge=1)

    @classmethod
    def from_env(cls) -> Config:
        api_key = os.getenv("LLM_API_KEY") or os.getenv("GLM_API_KEY")
        if not api_key:
            raise ValueError("LLM_API_KEY (or legacy GLM_API_KEY) is required")
        temperature = os.getenv("LLM_TEMPERATURE") or os.getenv("GLM_TEMPERATURE") or "0.2"
        return cls(
            glm_api_key=api_key,
            glm_model=os.getenv("LLM_MODEL") or os.getenv("GLM_MODEL", "deepseek-v4-pro"),
            glm_base_url=os.getenv("LLM_BASE_URL")
            or os.getenv("GLM_BASE_URL", "https://api.ai-native-x.site/v1"),
            temperature=float(temperature),
            max_concurrent_agents=int(os.getenv("REVIEWCREW_MAX_AGENTS", "4")),
            pipeline_timeout_seconds=int(os.getenv("REVIEWCREW_TIMEOUT", "600")),
        )
