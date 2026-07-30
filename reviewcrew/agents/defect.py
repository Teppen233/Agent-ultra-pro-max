"""DefectAgent —— 使用 LLM 进行技术缺陷审查。

负责发现：
- 安全漏洞：SQL 注入、XSS、SSRF、路径穿越、越权
- 内存与资源：泄漏、无界集合、未关闭连接
- 并发安全：竞态条件、死锁风险
- 错误处理：过宽捕获、空处理、信息泄露
- 代码质量：空指针、未定义行为、类型错误
"""

from __future__ import annotations

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

DEFECT_SYSTEM_PROMPT = """你是一个资深代码安全审查专家。你的任务是审查 PR 代码变更，发现技术缺陷和安全漏洞。

审查重点：
1. SQL 注入：字符串拼接构造 SQL、未使用参数化查询
2. XSS：未转义的用户输入输出到 HTML/JS
3. SSRF：用户可控的 URL 请求
4. 路径穿越：未校验的文件路径访问
5. 认证/授权：缺少权限检查、Token 泄露
6. 资源泄漏：未关闭的文件/连接、无界集合
7. 并发安全：竞态条件、非原子操作
8. 错误处理：过宽 except、空 catch、敏感信息泄露
9. 硬编码凭证：API Key、密码、Token 明文
10. 不安全的反序列化：pickle、yaml.unsafe_load

对于每个发现，返回 JSON 格式：
{"findings": [{"title": "缺陷标题（中文）", "description": "详细描述问题和原理", "severity": "critical|high|medium|low", "category": "security|memory|reliability|logic", "file": "文件路径", "line_start": 起始行号, "line_end": 结束行号, "confidence": 0.0-1.0, "trigger_condition": "触发条件描述", "impact": "实际影响描述", "suggestion": "具体修复建议"}]}

如果没有发现任何问题，返回 {"findings": []}。

注意：
- severity 要准确：critical（可导致系统被攻击/数据泄露）、high（严重 bug）、medium（潜在风险）、low（代码质量问题）
- confidence 基于证据充分程度：看到确切代码行=0.9+，推测=0.6-0.8
- 只报告确切的缺陷，不要猜测
- file 使用 PR diff 中给出的文件路径
- line_start/line_end 必须是整数"""


class DefectAgent(AgentRuntime):
    """缺陷审查 Agent —— 技术缺陷发现专家。"""

    role = "defect"

    def __init__(self, model: Any, agent_id: str = "defect-1") -> None:
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
        """对 ContextPack(s) 进行 LLM 缺陷审查。

        Args:
            context: 单个审查上下文包
            contexts: 多个审查上下文包
            pr_data: PRData（用于获取 raw_diff）
            mailbox: Agent 消息邮箱（可选）
            blackboard: 共享证据黑板（可选）

        Returns:
            Finding 列表
        """
        packs = contexts if contexts else ([context] if context else [])
        if not packs:
            logger.warning("DefectAgent[%s] 没有 ContextPack，回退到空结果", self.agent_id)
            return []

        logger.info("DefectAgent[%s] 开始审查 %d 个 ContextPack", self.agent_id, len(packs))

        all_findings: list[Finding] = []

        for pack in packs:
            try:
                findings = await self._review_pack(pack, pr_data)
                all_findings.extend(findings)
                logger.info("DefectAgent[%s] 文件 %s 发现 %d 个缺陷",
                            self.agent_id, pack.files, len(findings))
            except Exception as e:
                logger.error("DefectAgent[%s] 审查 %s 失败: %s",
                             self.agent_id, pack.files, e)

        logger.info("DefectAgent[%s] 审查完成，共发现 %d 个缺陷",
                     self.agent_id, len(all_findings))
        return all_findings

    async def _review_pack(self, pack: ContextPack, pr_data: Any = None) -> list[Finding]:
        """审查单个 ContextPack。"""
        prompt = self._build_prompt(pack, pr_data)
        response = await self._call_llm(prompt)
        return self._parse_findings(response, pack)

    def _build_prompt(self, pack: ContextPack, pr_data: Any = None) -> str:
        """构建审查 prompt。"""
        parts: list[str] = []

        # PR 概述
        if pack.pr_title:
            parts.append(f"## PR 标题\n{pack.pr_title}")
        if pack.pr_description:
            parts.append(f"## PR 描述\n{pack.pr_description}")

        # 文件列表
        parts.append(f"## 变更文件\n{chr(10).join('- ' + f for f in pack.files)}")

        # Diff hunks
        parts.append("## Diff 变更")
        for hunk in pack.diff_hunks:
            parts.append(f"### {hunk.file} (行 {hunk.new_start}-{hunk.new_start + hunk.new_count})")
            parts.append(f"```\n{hunk.content}\n```")

        # 封闭代码（更大上下文）
        if pack.enclosing_code:
            parts.append("## 变更代码上下文")
            for ev in pack.enclosing_code:
                parts.append(f"### {ev.file}:{ev.line_start}-{ev.line_end}")
                parts.append(f"```{ev.language or ''}\n{ev.content}\n```")

        # 相关文件
        if pack.related_code:
            parts.append("## 同目录相关代码")
            for ev in pack.related_code[:3]:  # 限制 3 个
                parts.append(f"### {ev.file}:{ev.line_start}-{ev.line_end}")
                parts.append(f"```{ev.language or ''}\n{ev.content[:2000]}\n```")

        return "\n\n".join(parts)

    async def _call_llm(self, user_prompt: str) -> str:
        """调用 LLM API 并返回原始响应文本。"""
        if not hasattr(self, '_config'):
            from ..config import Config
            self._config = Config.from_env()

        config = self._config
        url = f"{config.llm_base_url.rstrip('/')}/v1/chat/completions"
        api_key = config.llm_api_key.get_secret_value()

        if not api_key:
            raise ValueError("LLM_API_KEY 未配置，无法调用 LLM")

        payload = {
            "model": config.llm_model_name,
            "messages": [
                {"role": "system", "content": DEFECT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
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

        content = data["choices"][0]["message"]["content"]
        return content

    def _parse_findings(self, response: str, pack: ContextPack) -> list[Finding]:
        """从 LLM 响应中解析 Finding 列表。"""
        # 提取 JSON 块
        json_str = response
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0]

        try:
            data = json.loads(json_str.strip())
        except json.JSONDecodeError:
            logger.warning("DefectAgent[%s] LLM 响应不是有效 JSON: %.200s...",
                           self.agent_id, response)
            return []

        findings_data = data.get("findings", [])
        if not isinstance(findings_data, list):
            return []

        findings: list[Finding] = []
        for item in findings_data:
            try:
                # 确保文件路径匹配 ContextPack 中的文件
                file_path = item.get("file", pack.files[0] if pack.files else "unknown")
                finding = Finding(
                    id=f"find-{uuid.uuid4().hex[:8]}",
                    producer="defect",
                    category=item.get("category", "logic"),
                    severity=item.get("severity", "medium"),
                    confidence=float(item.get("confidence", 0.7)),
                    file=file_path,
                    line_start=int(item.get("line_start", 1)),
                    line_end=int(item.get("line_end", item.get("line_start", 1))),
                    title=item.get("title", "未命名缺陷"),
                    description=item.get("description", ""),
                    trigger_condition=item.get("trigger_condition", ""),
                    impact=item.get("impact", ""),
                    reasoning_summary=item.get("reasoning_summary",
                                               f"LLM 缺陷检测 Agent 在 {file_path} 中发现潜在问题"),
                    suggestion=item.get("suggestion"),
                    evidence=[
                        CodeEvidence(
                            file=file_path,
                            line_start=int(item.get("line_start", 1)),
                            line_end=int(item.get("line_end", item.get("line_start", 1))),
                            content=item.get("description", "")[:500],
                            language="",
                        )
                    ],
                )
                findings.append(finding)
            except (ValueError, KeyError, TypeError) as e:
                logger.warning("DefectAgent[%s] 解析 Finding 失败: %s, item=%.200s",
                               self.agent_id, e, str(item))

        return findings
