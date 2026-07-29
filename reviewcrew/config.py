"""集中管理 ReviewCrew 的运行配置。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


AgentRole = Literal["team_lead", "defect", "intent", "verifier"]


class Config(BaseSettings):
    """从环境变量读取并校验系统配置。

    所有模型相关字段都可以在不修改代码的情况下覆盖。密钥使用
    ``SecretStr`` 保存，避免在对象展示和日志中意外泄露。
    """

    model_config = SettingsConfigDict(
        env_prefix="REVIEWCREW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: str = "openai-compatible"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr | None = None
    llm_model: str = "deepseek-v4-pro"
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    llm_timeout_seconds: float = Field(default=120.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=10)
    llm_output_mode: Literal["tool", "prompted"] = "prompted"

    team_lead_model: str | None = None
    defect_model: str | None = None
    intent_model: str | None = None
    verifier_model: str | None = None

    global_timeout_seconds: int = Field(default=600, gt=0)
    pr_load_timeout_seconds: int = Field(default=30, gt=0)
    context_timeout_seconds: int = Field(default=90, gt=0)
    review_timeout_seconds: int = Field(default=300, gt=0)
    collaboration_window_seconds: float = Field(default=125.0, gt=0)
    verifier_timeout_seconds: int = Field(default=120, gt=0)
    report_timeout_seconds: int = Field(default=30, gt=0)
    max_concurrency: int = Field(default=4, gt=0, le=32)
    context_character_budget: int = Field(default=120_000, gt=0)

    runs_dir: Path = Path("runs")
    github_token: SecretStr | None = None

    @model_validator(mode="after")
    def validate_collaboration_window(self) -> "Config":
        """保证专家仍在线等待 Verifier 首次裁决后可能发出的补证请求。"""

        if self.collaboration_window_seconds < self.llm_timeout_seconds:
            raise ValueError("专家协作窗口不得短于单次模型超时")
        return self

    @classmethod
    def from_env(cls) -> "Config":
        """根据当前环境变量构造配置对象。"""

        return cls()

    def model_for(self, role: AgentRole) -> str:
        """返回指定 Agent 使用的模型，未覆盖时回退到全局模型。"""

        role_model = getattr(self, f"{role}_model")
        return role_model or self.llm_model
