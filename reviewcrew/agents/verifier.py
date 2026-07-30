"""VerifierAgent —— 使用 LLM 独立验证候选 Finding。

对每个候选 Finding 进行二次验证：
1. 是否由当前 PR 引入
2. 触发路径是否可达
3. 严重度和置信度是否合理
4. 是否是误报
5. 修复建议是否可行
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import Config
from ..schemas import Finding, Verdict
from ..team.mailbox import Mailbox
from ..team.blackboard import EvidenceBlackboard
from .base import AgentRuntime

logger = logging.getLogger(__name__)

VERIFIER_SYSTEM_PROMPT = """你是一个代码审查结果验证专家。对缺陷报告进行独立二次验证。

判断标准：
1. 该缺陷是否确实存在于代码中
2. 严重度 (severity) 是否合理
3. 置信度 (confidence) 是否合理

你必须只返回一个 JSON 对象，不要有任何其他文字：
{"verdict": "confirmed|likely|false_positive|insufficient_evidence", "adjusted_severity": "critical|high|medium|low", "adjusted_confidence": 0.85, "reason": "简短理由"}

verdict 含义：
- confirmed: 确实存在，证据充分
- likely: 很可能存在但需要更多上下文
- false_positive: 误报
- insufficient_evidence: 证据不足"""


class VerifierAgent(AgentRuntime):
    """验证 Agent —— 独立验证候选 Finding。"""

    role = "verifier"

    def __init__(self, model: Any, agent_id: str = "verifier-1") -> None:
        super().__init__(model)
        self.agent_id = agent_id

    async def run(
        self,
        mailbox: Mailbox | None = None,
        blackboard: EvidenceBlackboard | None = None,
    ) -> list[Verdict]:
        """完整验证流程（预留接口，当前由 verify_finding 逐条处理）。"""
        return []

    async def verify_finding(self, finding: Finding, context_prompt: str = "") -> Verdict:
        """验证单个候选 Finding。

        Args:
            finding: 候选 Finding
            context_prompt: 附加上下文（如 PR 描述、相关代码）

        Returns:
            验证判决
        """
        logger.info("VerifierAgent[%s] 验证 Finding: %s", self.agent_id, finding.id)

        prompt = self._build_verify_prompt(finding, context_prompt)

        try:
            response = await self._call_llm(prompt)
            verdict = self._parse_verdict(response, finding)
        except Exception as e:
            logger.warning("VerifierAgent[%s] LLM 验证失败，降级为置信度过滤: %s",
                           self.agent_id, e)
            # 降级：置信度 >= 0.6 → accepted
            verdict = Verdict(
                finding_id=finding.id,
                accepted=finding.confidence >= 0.6,
                verdict="likely" if finding.confidence >= 0.6 else "insufficient_evidence",
                confidence=finding.confidence,
                severity=finding.severity,
                reason=f"LLM 验证不可用，降级为置信度过滤 (threshold=0.6, actual={finding.confidence:.0%})",
            )

        logger.info("VerifierAgent[%s] %s -> %s (confidence: %.0f%%)",
                     self.agent_id, finding.id, verdict.verdict, verdict.confidence * 100)
        return verdict

    def _build_verify_prompt(self, finding: Finding, context: str) -> str:
        """构建验证 prompt。"""
        parts = [
            "## 待验证的缺陷报告",
            f"- ID: {finding.id}",
            f"- 来源: {finding.producer}",
            f"- 严重度: {finding.severity}",
            f"- 置信度: {finding.confidence:.0%}",
            f"- 类别: {finding.category}",
            f"- 文件: {finding.file}:{finding.line_start}-{finding.line_end}",
            f"- 标题: {finding.title}",
            f"- 描述: {finding.description}",
            f"- 触发条件: {finding.trigger_condition}",
            f"- 影响: {finding.impact}",
        ]
        if finding.suggestion:
            parts.append(f"- 修复建议: {finding.suggestion}")
        if context:
            parts.append(f"\n## 附加上下文\n{context[:3000]}")

        return "\n".join(parts)

    async def _call_llm(self, user_prompt: str) -> str:
        """调用 LLM API。"""
        if not hasattr(self, '_config'):
            from ..config import Config
            self._config = Config.from_env()

        config = self._config
        url = f"{config.llm_base_url.rstrip('/')}/v1/chat/completions"
        api_key = config.llm_api_key.get_secret_value()

        if not api_key:
            raise ValueError("LLM_API_KEY 未配置")

        payload = {
            "model": config.llm_model_name,
            "messages": [
                {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 1024,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        return data["choices"][0]["message"]["content"]

    def _parse_verdict(self, response: str, finding: Finding) -> Verdict:
        """从 LLM 响应中解析 Verdict，支持纯 JSON 和混合文本。"""
        # 尝试多种方式提取 JSON
        json_str = ""
        # 1. ```json 代码块
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0]
        else:
            # 2. 查找第一个 { 到最后一个 }
            start = response.find("{")
            end = response.rfind("}")
            if start >= 0 and end > start:
                json_str = response[start:end+1]
            else:
                json_str = response

        try:
            data = json.loads(json_str.strip())
        except json.JSONDecodeError:
            logger.warning("VerifierAgent[%s] JSON 解析失败，尝试从文本推断: %.200s",
                           self.agent_id, response)
            # 降级：从文本中推断 verdict
            text = response.lower()
            if any(w in text for w in ["误报", "false_positive", "不存在", "没有问题", "不是问题"]):
                return Verdict(finding_id=finding.id, accepted=False,
                               verdict="false_positive", confidence=finding.confidence,
                               severity=finding.severity, reason=response[:200])
            if any(w in text for w in ["确认", "confirmed", "确实存在", "正确"]):
                return Verdict(finding_id=finding.id, accepted=True,
                               verdict="confirmed", confidence=finding.confidence,
                               severity=finding.severity, reason=response[:200])
            # 默认降级接受
            logger.warning("VerifierAgent[%s] 无法判断，降级接受", self.agent_id)
            return Verdict(finding_id=finding.id, accepted=True,
                           verdict="likely", confidence=finding.confidence,
                           severity=finding.severity, reason="LLM 响应无明确结论，降级接受")

        return Verdict(
            finding_id=finding.id,
            accepted=data.get("verdict", "likely") in ("confirmed", "likely"),
            verdict=data.get("verdict", "likely"),
            confidence=data.get("adjusted_confidence", finding.confidence),
            severity=data.get("adjusted_severity", finding.severity),
            reason=data.get("reason", "LLM 验证完成"),
            final_finding=None,
        )
