"""围绕 PR 修改行构建可裁剪的 ContextPack。"""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path
import re

from reviewcrew.config import Config
from reviewcrew.schemas import CodeEvidence, ContextPack, DiffHunk, PRData
from reviewcrew.tools.files import ToolAccessError, safe_read
from reviewcrew.tools.search import find_related_tests, search_code, search_project_docs
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
        related_code = _find_related_code(repo, changed_file.path, changed_file.hunks)
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
            related_code=related_code,
            related_tests=related_tests,
            project_docs=docs,
            static_signals=[signal for signal in signals if signal.file.replace("\\", "/") == changed_file.path],
            retrieval_notes=notes,
        )
        packs.append(_fit_budget(pack, config.context_character_budget))
    return packs


_DECLARATION_PATTERNS = (
    re.compile(r"^\+\s*(?:export\s+)?(?:async\s+)?(?:def|class|function)\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"^\+\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*="),
    re.compile(r"^\+\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\("),
    re.compile(r"^\+\s*(?:(?:public|protected|private|static|final|synchronized)\s+)+(?:[\w<>?,.\[\]]+\s+)+([A-Za-z_]\w*)\s*\("),
)
_CODE_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".vue", ".go", ".java",
    ".rb", ".rs", ".c", ".h", ".cpp", ".hpp",
}


def _find_related_code(repo: Path, changed_path: str, hunks: list[DiffHunk]) -> list[CodeEvidence]:
    """从新增声明提取少量符号，并检索当前文件之外的稳定引用证据。"""

    symbols: list[str] = []
    for line in (line for hunk in hunks for line in hunk.content.splitlines()):
        for pattern in _DECLARATION_PATTERNS:
            match = pattern.match(line)
            if match is not None and match.group(1) not in symbols:
                symbols.append(match.group(1))
                break
        if len(symbols) == 3:
            break

    selected: list[CodeEvidence] = []
    seen: set[tuple[str, int, int, str | None]] = set()
    for symbol in symbols:
        for evidence in search_code(repo, symbol, limit=20):
            if evidence.file == changed_path or Path(evidence.file).suffix.lower() not in _CODE_SUFFIXES:
                continue
            key = (
                evidence.file,
                evidence.start_line,
                evidence.end_line,
                evidence.content_hash,
            )
            if key in seen:
                continue
            seen.add(key)
            selected.append(evidence.model_copy(update={"source": "related_code"}))
            if len(selected) == 10:
                return selected
    return selected


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
