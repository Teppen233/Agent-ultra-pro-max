"""IntentAgent —— 使用 LLM 进行意图对齐和业务逻辑审查。

负责发现：
- 业务逻辑错误：需求、测试和实现行为不一致
- 边界条件：缺少空值检查、越界访问、极端输入
- 状态转换：非法状态、状态遗漏
- 架构问题：循环依赖、接口破坏、向后兼容性
- 代码意图：注释与代码不一致、变量名误导
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

import httpx

from ..config import Config
from ..schemas import ContextPack, Finding, CodeEvidence, AgentSnapshot
from ..team.mailbox import Mailbox
from ..team.blackboard import EvidenceBlackboard
from .base import AgentRuntime

logger = logging.getLogger(__name__)

INTENT_SYSTEM_PROMPT = """你是一个资深代码逻辑审查专家。审查 PR diff，发现逻辑错误和意图不一致。

审查重点：
1. 行为变更：重构前后逻辑是否等价，条件组合是否一致
2. 边界条件：方法提取后 null 检查是否完整，空集合处理
3. 接口兼容：可见性变更 (protected→public) 是否合理
4. 逻辑漏洞：分支遗漏、条件反转、状态转换不完整
5. 代码意图：PR 标题与代码变更是否一致

你必须只返回一个 JSON 对象，不要有任何其他文字：
{"findings": [{"title": "中文标题", "description": "详细描述", "severity": "critical|high|medium|low", "category": "business_logic|logic|architecture|reliability", "file": "文件路径", "line_start": 行号, "line_end": 行号, "confidence": 0.8, "trigger_condition": "触发条件", "impact": "实际影响", "suggestion": "修复建议"}]}

如果没有问题，返回 {"findings": []}。

注意：
- 不重复缺陷检测 Agent 的安全审查
- 重点关注 diff 中条件判断的变化（&&、||、!）
- 方法提取后参数是否有遗漏"""


class IntentAgent(AgentRuntime):
    """意图审查 Agent —— 语义和逻辑发现专家。"""

    role = "intent"

    def __init__(self, model: Any, agent_id: str = "intent-1") -> None:
        super().__init__(model)
        self.agent_id = agent_id

    async def run(
        self,
        context: ContextPack | None = None,
        contexts: list[ContextPack] | None = None,
        pr_data: Any = None,
        mailbox: Mailbox | None = None,
        blackboard: EvidenceBlackboard | None = None,
    ) -> list[Finding]:
        """对 ContextPack(s) 进行 LLM 意图/逻辑审查。

        Args:
            context: 单个审查上下文包
            contexts: 多个审查上下文包
            pr_data: PRData（用于获取 PR 标题/描述）
            mailbox: Agent 消息邮箱（可选）
            blackboard: 共享证据黑板（可选）

        Returns:
            Finding 列表
        """
        packs = contexts if contexts else ([context] if context else [])
        if not packs:
            logger.warning("IntentAgent[%s] 没有 ContextPack", self.agent_id)
            return []

        logger.info("IntentAgent[%s] 开始审查 %d 个 ContextPack", self.agent_id, len(packs))

        all_findings: list[Finding] = []

        for pack in packs:
            try:
                findings = await self._review_pack(pack, pr_data)
                all_findings.extend(findings)
                logger.info("IntentAgent[%s] 文件 %s 发现 %d 个逻辑问题",
                            self.agent_id, pack.files, len(findings))
            except Exception as e:
                logger.error("IntentAgent[%s] 审查 %s 失败: %s",
                             self.agent_id, pack.files, e)

        logger.info("IntentAgent[%s] 审查完成，共发现 %d 个逻辑问题",
                     self.agent_id, len(all_findings))
        return all_findings

    async def _review_pack(self, pack: ContextPack, pr_data: Any = None) -> list[Finding]:
        """审查单个 ContextPack。"""
        prompt = self._build_prompt(pack, pr_data)
        response = await self._call_llm(prompt)
        return self._parse_findings(response, pack)

    def _build_prompt(self, pack: ContextPack, pr_data: Any = None) -> str:
        """构建意图审查 prompt（限制总长度 < 8000 字符）。"""
        parts: list[str] = []
        limit = 8000

        parts.append("## 审查任务\n分析以下 PR 是否存在逻辑错误、行为变更不一致、null 检查遗漏。")
        if pack.pr_title:
            parts.append(f"**PR 标题**: {pack.pr_title[:200]}")
        if pack.pr_description:
            parts.append(f"**PR 描述**: {pack.pr_description[:500]}")

        parts.append(f"## 变更文件\n{', '.join(pack.files[:10])}")

        # Diff hunks（截断）
        hunk_parts = ["## Diff 变更"]
        for hunk in pack.diff_hunks[:5]:
            content = hunk.content[:1500]
            hunk_parts.append(f"### {hunk.file} (+{hunk.new_start})")
            hunk_parts.append(f"```\n{content}\n```")
        parts.append("\n".join(hunk_parts))

        full = "\n\n".join(parts)
        if len(full) > limit:
            full = full[:limit] + "\n... (已截断)"
        return full

    async def _call_llm(self, user_prompt: str) -> str:
        """调用 LLM API，失败重试 2 次。"""
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
                {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
        }

        last_error = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(url, headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    }, json=payload)
                    resp.raise_for_status()
                    return resp.json()["choices"][0]["message"]["content"]
            except Exception as e:
                last_error = e
                logger.warning("IntentAgent LLM 失败 (attempt %d/3): %s", attempt + 1, e)
                if attempt < 2:
                    await asyncio.sleep(2)

        raise RuntimeError(f"LLM 调用失败: {last_error}")

    def _parse_findings(self, response: str, pack: ContextPack) -> list[Finding]:
        """从 LLM 响应中解析 Finding 列表。"""
        json_str = response
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0]

        try:
            data = json.loads(json_str.strip())
        except json.JSONDecodeError:
            logger.warning("IntentAgent[%s] 非 JSON 响应: %.200s...", self.agent_id, response)
            return []

        findings_data = data.get("findings", [])
        if not isinstance(findings_data, list):
            return []

        findings: list[Finding] = []
        for item in findings_data:
            try:
                file_path = item.get("file", pack.files[0] if pack.files else "unknown")
                ls = max(1, int(item.get("line_start", 1) or 1))
                le = max(ls, int(item.get("line_end", ls) or ls))
                finding = Finding(
                    id=f"find-{uuid.uuid4().hex[:8]}",
                    producer="intent",
                    category=item.get("category", "logic"),
                    severity=item.get("severity", "medium"),
                    confidence=float(item.get("confidence", 0.7)),
                    file=file_path,
                    line_start=ls,
                    line_end=le,
                    title=item.get("title", "逻辑问题"),
                    description=item.get("description", ""),
                    trigger_condition=item.get("trigger_condition", ""),
                    impact=item.get("impact", ""),
                    reasoning_summary=item.get("reasoning_summary",
                                               f"LLM 意图分析 Agent 在 {file_path} 中发现逻辑问题"),
                    suggestion=item.get("suggestion"),
                    evidence=[
                        CodeEvidence(
                            file=file_path,
                            line_start=ls,
                            line_end=le,
                            content=item.get("description", "")[:500],
                            language="",
                        )
                    ],
                )
                findings.append(finding)
            except (ValueError, KeyError, TypeError) as e:
                logger.warning("IntentAgent[%s] 解析 Finding 失败: %s", self.agent_id, e)

        return findings
