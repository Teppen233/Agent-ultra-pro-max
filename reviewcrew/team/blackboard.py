"""共享证据 Blackboard —— Agent 间共享的结构化事实和状态。

Blackboard 只保存结构化事实、证据和状态，不保存隐藏思维链。
Agent 通过 Blackboard 发布发现、读取其他 Agent 的证据和状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..schemas import CodeEvidence, Finding, StaticSignal


@dataclass
class BlackboardEntry:
    """Blackboard 中的一条记录。"""

    key: str
    value: Any
    source: str  # 写入 Agent 名称
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EvidenceBlackboard:
    """共享证据黑板 —— Agent Team 的结构化共享内存。

    只保存公开的结构化数据：
    - 候选 Finding
    - 代码证据
    - 静态信号
    - Agent 状态
    - 覆盖信息

    不保存模型隐藏思维链、完整 Prompt 或私密推理。
    """

    def __init__(self) -> None:
        self._entries: dict[str, BlackboardEntry] = {}
        self._findings: dict[str, Finding] = {}
        self._signals: list[StaticSignal] = []
        self._coverage: set[str] = set()

    # ---- 写入 ----

    def apply(self, key: str, value: Any, source: str = "unknown") -> None:
        """写入或更新一条 Blackboard 记录。

        Args:
            key: 记录键
            value: 记录值
            source: 写入的 Agent 名称
        """
        self._entries[key] = BlackboardEntry(key=key, value=value, source=source)

    def add_finding(self, finding: Finding, source: str) -> None:
        """发布候选 Finding 到 Blackboard。

        Args:
            finding: 候选 Finding
            source: 发布的 Agent 名称
        """
        self._findings[finding.id] = finding
        self.apply(f"finding:{finding.id}", finding, source=source)

    def add_signal(self, signal: StaticSignal) -> None:
        """添加静态分析信号。

        Args:
            signal: 来自 Semgrep 等工具的静态信号
        """
        self._signals.append(signal)
        self.apply(f"signal:{signal.rule_id}:{signal.file}:{signal.line}", signal, source=signal.tool)

    def add_coverage(self, dimension: str) -> None:
        """记录已覆盖的审查维度。

        Args:
            dimension: 维度名称，如 "security", "logic", "architecture"
        """
        self._coverage.add(dimension)

    # ---- 读取 ----

    def get(self, key: str) -> Any | None:
        """读取单条记录。"""
        entry = self._entries.get(key)
        return entry.value if entry else None

    def get_finding(self, finding_id: str) -> Finding | None:
        """按 ID 获取候选 Finding。"""
        return self._findings.get(finding_id)

    def get_all_findings(self) -> list[Finding]:
        """获取所有候选 Finding。"""
        return list(self._findings.values())

    def get_signals_for_file(self, file_path: str) -> list[StaticSignal]:
        """获取指定文件的静态信号。"""
        return [s for s in self._signals if s.file == file_path]

    def get_coverage(self) -> list[str]:
        """获取已覆盖的审查维度列表。"""
        return sorted(self._coverage)

    # ---- 状态 ----

    def snapshot(self) -> dict[str, Any]:
        """生成 Blackboard 当前状态的快照。"""
        return {
            "entry_count": len(self._entries),
            "finding_count": len(self._findings),
            "signal_count": len(self._signals),
            "coverage": self.get_coverage(),
        }

    def clear(self) -> None:
        """清空 Blackboard（用于测试重置）。"""
        self._entries.clear()
        self._findings.clear()
        self._signals.clear()
        self._coverage.clear()
