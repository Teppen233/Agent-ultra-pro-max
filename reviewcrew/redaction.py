"""为所有磁盘审计与报告边界提供统一的敏感内容脱敏。"""

from __future__ import annotations

import re
from typing import Any


_SENSITIVE_KEYS = {
    "reasoning_summary",
    "prompt",
    "raw_prompt",
    "raw_response",
    "model_response",
    "chain_of_thought",
    "思维链",
    "模型响应",
}
_SENSITIVE_TEXT = re.compile(
    r"reasoning_summary|chain[-_ ]of[-_ ]thought|raw_response|"
    r"(?:完整|full)\s*(?:prompt|模型响应)|思维链",
    re.IGNORECASE,
)


def redact_sensitive_text(value: str) -> str:
    """敏感标记一旦出现就丢弃整段文本，避免残留相邻私密内容。"""

    return "[已脱敏]" if _SENSITIVE_TEXT.search(value) else value


def sanitize_persisted_value(value: Any) -> Any:
    """递归生成可落盘副本，移除内部推理、Prompt 和模型响应。"""

    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized = key.casefold()
            if normalized in _SENSITIVE_KEYS:
                continue
            sanitized[key] = sanitize_persisted_value(item)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_persisted_value(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value
