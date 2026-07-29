"""静态审查引擎 —— 基于规则的代码审查，不依赖 LLM。

用于 Fake 模式和 LLM 不可用时的降级审查。
扫描 diff 中的常见模式：SQL 注入、硬编码密钥、资源泄漏等。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from ..schemas import Finding, CodeEvidence, PRData, DiffHunk


@dataclass
class RuleCheck:
    """审查规则定义。"""
    id: str
    name: str  # 中文规则名
    category: str
    severity: str
    patterns: list[str]  # 正则列表
    description_template: str
    suggestion: str


# 内置审查规则
_RULES: list[RuleCheck] = [
    RuleCheck(
        id="sql-injection",
        name="SQL 注入风险",
        category="security",
        severity="high",
        patterns=[
            r'(?:execute|executemany)\s*\(\s*(?:f["\']|["\'].*%.*)',
            r'(?:query|execute)\s*\(\s*["\'].*\+.*["\']',
            r'\.format\s*\(.*\)\s*\.\s*(?:execute|query)',
            r'f["\'].*SELECT.*\{.*\}',
            r'f["\'].*INSERT.*\{.*\}',
        ],
        description_template="发现 SQL 查询使用字符串拼接或格式化，可能导致 SQL 注入漏洞",
        suggestion="使用参数化查询（? 占位符 + 参数绑定）替代字符串拼接",
    ),
    RuleCheck(
        id="hardcoded-secret",
        name="硬编码密钥",
        category="security",
        severity="critical",
        patterns=[
            r'(?:password|secret|api_key|apikey|token|auth)\s*=\s*["\'][^"\']{8,}["\']',
            r'(?:PASSWORD|SECRET|API_KEY|TOKEN)\s*=\s*["\']',
        ],
        description_template="发现代码中硬编码了密钥或敏感凭证",
        suggestion="使用环境变量或密钥管理服务存储敏感信息",
    ),
    RuleCheck(
        id="bare-except",
        name="过宽的异常捕获",
        category="reliability",
        severity="medium",
        patterns=[
            r'except\s*:',
            r'except\s+Exception\s*:',
        ],
        description_template="发现过于宽泛的异常捕获，可能隐藏关键错误",
        suggestion="只捕获已知的异常类型，并在 except 块中记录日志",
    ),
    RuleCheck(
        id="resource-leak",
        name="资源泄漏风险",
        category="memory",
        severity="medium",
        patterns=[
            r'open\s*\([^)]+\)(?!.*\bwith\b)',
            r'(?:connect|connection|cursor)\s*=\s*(?!.*\bwith\b)',
        ],
        description_template="文件或连接资源未使用 with 语句管理，可能泄漏",
        suggestion="使用 with 语句或 try-finally 确保资源释放",
    ),
    RuleCheck(
        id="unchecked-input",
        name="未校验的用户输入",
        category="security",
        severity="high",
        patterns=[
            r'request\.(?:args|form|json|data)\s*\[',
            r'request\.(?:args|form|json|data)\.get\(',
            r'@app\.\w+\s*\n\s*def\s+\w+\((?!.*\bvalidate\b)',
        ],
        description_template="用户输入未经验证直接使用，可能导致注入或越权",
        suggestion="在处理请求参数前进行类型校验和范围限制",
    ),
    RuleCheck(
        id="empty-error-handling",
        name="空的异常/错误处理",
        category="logic",
        severity="low",
        patterns=[
            r'except\s+\w+.*:',
            r'\.catch\s*\(\s*\)',
        ],
        description_template="异常被捕获后未做任何处理，问题被静默忽略",
        suggestion="在异常处理中至少记录日志，或重新抛出无法处理的异常",
    ),
]


def run_static_review(pr: PRData) -> tuple[list[Finding], int]:
    """对 PR 执行静态规则审查。

    Args:
        pr: PR 数据

    Returns:
        (findings, rule_hits) — Finding 列表和命中的规则数
    """
    findings: list[Finding] = []
    rule_hits = 0

    for rule in _RULES:
        for f in pr.files:
            for hunk in f.hunks:
                # 只检查变更行
                added_lines = _extract_additions(hunk)
                for line_no, content in added_lines:
                    for pattern in rule.patterns:
                        if re.search(pattern, content, re.IGNORECASE):
                            finding = Finding(
                                id=f"find-{uuid.uuid4().hex[:8]}",
                                producer="defect",
                                category=rule.category,
                                severity=rule.severity,
                                confidence=0.75,
                                file=f.path,
                                line_start=line_no,
                                line_end=line_no,
                                title=rule.name,
                                description=rule.description_template,
                                trigger_condition=f"规则 {rule.id} 在第 {line_no} 行命中",
                                impact="可能导致安全漏洞、资源泄漏或运行时错误",
                                reasoning_summary=(
                                    f"静态规则 {rule.name} 命中："
                                    f"文件 {f.path} 第 {line_no} 行"
                                ),
                                suggestion=rule.suggestion,
                                evidence=[
                                    CodeEvidence(
                                        file=f.path,
                                        line_start=line_no,
                                        line_end=line_no,
                                        content=content.strip(),
                                        language=_guess_language(f.path),
                                    )
                                ],
                            )
                            findings.append(finding)
                            rule_hits += 1

    return findings, rule_hits


def _extract_additions(hunk: DiffHunk) -> list[tuple[int, str]]:
    """从 DiffHunk 中提取新增行及其在新文件中的行号。

    返回 (行号, 行内容) 列表。
    """
    results: list[tuple[int, str]] = []
    new_line = hunk.new_start

    for line in hunk.content.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            results.append((new_line, line[1:]))
            new_line += 1
        elif line.startswith("-") or line.startswith("---"):
            continue
        else:
            new_line += 1

    return results


def _guess_language(path: str) -> str:
    """根据文件扩展名推断语言。"""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return {
        "py": "python", "js": "javascript", "ts": "typescript",
        "go": "go", "java": "java", "rb": "ruby", "rs": "rust",
        "vue": "vue", "sql": "sql", "sh": "bash", "yaml": "yaml",
        "yml": "yaml", "json": "json", "md": "markdown",
    }.get(ext, "")
