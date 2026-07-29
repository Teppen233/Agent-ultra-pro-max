"""围绕 PR 修改行构建可裁剪的 ContextPack。"""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path

from reviewcrew.config import Config
from reviewcrew.schemas import CodeEvidence, ContextPack, PRData
from reviewcrew.tools.files import ToolAccessError, safe_read
from reviewcrew.tools.search import find_related_tests, search_project_docs
from reviewcrew.tools.semgrep import run_semgrep


async def build_context(pr: PRData, repo: Path, config: Config) -> list[ContextPack]:
    """按修改文件构建上下文，并遵守单 Pack 字符预算。"""

    docs = search_project_docs(repo)
    signals = await run_semgrep(repo, [item.path for item in pr.files], timeout=60)
    packs: list[ContextPack] = []
    for changed_file in pr.files:
        enclosing: list[CodeEvidence] = []
        notes: list[str] = []
        for hunk in changed_file.hunks:
            start = max(1, hunk.new_start - 40)
            end = max(start, hunk.new_start + max(hunk.new_count, 1) + 40)
            try:
                enclosing.append(safe_read(repo, changed_file.path, start, end))
            except ToolAccessError as error:
                notes.append(f"无法读取修改文件上下文：{error}")
        related_tests = find_related_tests(repo, changed_file.path)
        pack = ContextPack(
            id=f"ctx-{sha1(f'{pr.head_sha}:{changed_file.path}'.encode()).hexdigest()[:12]}",
            repository=pr.repository,
            base_sha=pr.base_sha,
            head_sha=pr.head_sha,
            pr_title=pr.title,
            pr_description=pr.description,
            files=[changed_file.path],
            diff_hunks=changed_file.hunks,
            enclosing_code=enclosing,
            related_tests=related_tests,
            project_docs=docs,
            static_signals=[signal for signal in signals if signal.file.replace("\\", "/") == changed_file.path],
            retrieval_notes=notes,
        )
        packs.append(_fit_budget(pack, config.context_character_budget))
    return packs


def _fit_budget(pack: ContextPack, budget: int) -> ContextPack:
    """按证据优先级裁剪 ContextPack 到字符预算。"""

    if len(pack.model_dump_json()) <= budget:
        return pack
    pack.truncated = True
    pack.project_docs = []
    if len(pack.model_dump_json()) <= budget:
        return pack
    pack.related_tests = []
    if len(pack.model_dump_json()) <= budget:
        return pack
    pack.related_code = []
    pack.enclosing_code = [
        evidence.model_copy(update={"content": evidence.content[: max(0, budget // max(1, len(pack.enclosing_code)))]})
        for evidence in pack.enclosing_code
    ]
    return pack

