"""全局配置 —— 从环境变量读取所有运行参数。

所有时间单位均为秒，默认值遵循设计规范第 9 节预算表。
"""

from __future__ import annotations

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """ReviewCrew 全局配置，从环境变量和 .env 文件加载。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- LLM ----
    llm_base_url: str = Field(
        default="https://open.bigmodel.cn/api/paas/v4",
        description="OpenAI 兼容端点的 Base URL",
    )
    llm_model_name: str = Field(
        default="glm-4-flash",
        description="模型名称，可通过 LLM_MODEL_NAME 环境变量替换",
    )
    llm_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="API Key，通过 LLM_API_KEY 环境变量设置",
    )

    # ---- GitHub ----
    github_token: SecretStr = Field(
        default=SecretStr(""),
        description="GitHub Personal Access Token（公开仓库可选）",
    )

    # ---- 全局超时（秒） ----
    global_timeout_seconds: int = Field(
        default=600,
        ge=1,
        validation_alias="REVIEWCREW_GLOBAL_TIMEOUT_SECONDS",
        description="单次审查全局 watchdog 超时",
    )
    pr_load_timeout_seconds: int = Field(
        default=30,
        ge=1,
        validation_alias="REVIEWCREW_PR_LOAD_TIMEOUT_SECONDS",
        description="PR 加载和 Diff 解析超时",
    )
    context_timeout_seconds: int = Field(
        default=90,
        ge=1,
        validation_alias="REVIEWCREW_CONTEXT_TIMEOUT_SECONDS",
        description="上下文构建超时",
    )
    expert_timeout_seconds: int = Field(
        default=300,
        ge=1,
        validation_alias="REVIEWCREW_EXPERT_TIMEOUT_SECONDS",
        description="两专家并行审查超时",
    )
    verifier_timeout_seconds: int = Field(
        default=120,
        ge=1,
        validation_alias="REVIEWCREW_VERIFIER_TIMEOUT_SECONDS",
        description="Verifier 验证超时",
    )
    report_timeout_seconds: int = Field(
        default=30,
        ge=1,
        validation_alias="REVIEWCREW_REPORT_TIMEOUT_SECONDS",
        description="报告生成超时",
    )

    # ---- 并发 ----
    max_concurrent_experts: int = Field(
        default=3,
        ge=1,
        le=3,
        validation_alias="REVIEWCREW_MAX_CONCURRENT_EXPERTS",
        description="每个角色最多启动的分片数",
    )

    # ---- 运行目录 ----
    runs_dir: str = Field(
        default="runs",
        validation_alias="REVIEWCREW_RUNS_DIR",
        description="运行记录和事件的持久化目录",
    )

    # ---- 上下文 ----
    context_pack_char_budget: int = Field(
        default=8000,
        ge=1000,
        validation_alias="REVIEWCREW_CONTEXT_PACK_CHAR_BUDGET",
        description="单个 ContextPack 默认字符预算",
    )

    @model_validator(mode="after")
    def _validate_timeout_order(self) -> "Config":
        """各阶段超时之和不应超过全局超时（允许一定弹性，只做软警告）。"""
        stage_total = (
            self.pr_load_timeout_seconds
            + self.context_timeout_seconds
            + self.expert_timeout_seconds
            + self.verifier_timeout_seconds
            + self.report_timeout_seconds
        )
        if stage_total > self.global_timeout_seconds * 2:
            raise ValueError(
                f"各阶段超时之和 ({stage_total}s) 远超全局超时 "
                f"({self.global_timeout_seconds}s)，请检查配置"
            )
        return self

    def __repr__(self) -> str:
        """不暴露 API Key 等敏感字段。"""
        return (
            f"Config(llm_base_url={self.llm_base_url!r}, "
            f"llm_model_name={self.llm_model_name!r}, "
            f"global_timeout={self.global_timeout_seconds}s)"
        )

    @classmethod
    def from_env(cls) -> "Config":
        """从环境变量创建配置实例。"""
        return cls()
