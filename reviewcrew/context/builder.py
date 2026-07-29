"""Diff 中心上下文构建器 —— 围绕 PR 修改行组装审查上下文。

Context Builder 从 diff hunk 出发，收集：
- 修改符号的封闭代码
- 同目录相关代码
- 相关测试
- 项目文档片段
- Git 历史
- 静态信号

所有收集受字符预算约束，超出时标记 truncated。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from ..config import Config
from ..schemas import PRData, CodeEvidence, ContextPack, DiffHunk
from ..tools.files import safe_read


def _safe_resolve(repo: Path, relative: Path) -> Path | None:
    """安全解析相对路径，确保其位于仓库范围内。

    返回解析后的绝对路径，如果路径穿越到仓库外则返回 None。
    """
    full = (repo / relative).resolve()
    repo_resolved = repo.resolve()
    sep = "\\" if "\\" in str(repo_resolved) else "/"
    if not str(full).startswith(str(repo_resolved) + sep):
        return None
    return full


async def build_context(
    pr: PRData,
    repo: Path,
    config: Config,
) -> list[ContextPack]:
    """构建审查上下文包列表。

    按文件聚类 diff hunk，每个修改文件生成一个 ContextPack。

    Args:
        pr: 标准化 PR 数据
        repo: 仓库本地路径
        config: 全局配置

    Returns:
        ContextPack 列表，按文件聚类
    """
    packs: list[ContextPack] = []
    budget = config.context_pack_char_budget

    # 按文件分组 hunk
    file_hunks: dict[str, list[DiffHunk]] = {}
    for f in pr.files:
        if f.hunks:
            file_hunks[f.path] = f.hunks

    for file_path, hunks in file_hunks.items():
        pack_id = f"pack-{uuid.uuid4().hex[:8]}"
        truncated = False
        char_count = 0

        enclosing: list[CodeEvidence] = []
        related: list[CodeEvidence] = []

        # 收集修改符号周边代码
        for hunk in hunks:
            if hunk.changed_lines:
                try:
                    start = max(1, min(hunk.changed_lines) - 5)
                    end = max(hunk.changed_lines) + 5
                    evidence = safe_read(repo, file_path, start, end)
                    enclosing.append(evidence)
                    char_count += len(evidence.content)
                except (FileNotFoundError, ValueError):
                    continue

        # 尝试收集同目录相关文件（限制数量，防止路径穿越）
        file_dir = Path(file_path).parent
        resolved_dir = _safe_resolve(repo, file_dir)
        if resolved_dir is not None and resolved_dir.is_dir():
            try:
                for sibling in sorted(resolved_dir.iterdir())[:5]:
                    if sibling.is_file() and sibling.name != Path(file_path).name:
                        try:
                            evidence = safe_read(repo, str(sibling.relative_to(repo)), 1, 50)
                            related.append(evidence)
                            char_count += len(evidence.content)
                        except (FileNotFoundError, ValueError):
                            continue
            except (FileNotFoundError, OSError):
                pass

        # 检查预算
        if char_count > budget:
            truncated = True

        pack = ContextPack(
            id=pack_id,
            repository=pr.repository,
            base_sha=pr.base_sha,
            head_sha=pr.head_sha,
            pr_title=pr.title,
            pr_description=pr.description,
            files=[file_path],
            diff_hunks=hunks,
            enclosing_code=enclosing,
            related_code=related,
            related_tests=[],
            project_docs=[],
            git_history=[],
            static_signals=[],
            retrieval_notes=[
                f"收集了 {len(enclosing)} 个封闭代码片段, "
                f"{len(related)} 个相关文件片段"
            ],
            truncated=truncated,
        )
        packs.append(pack)

    return packs
