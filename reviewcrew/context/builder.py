"""围绕 PR 修改行构建可裁剪的 ContextPack。"""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path
import re
import shutil

from reviewcrew.config import Config
from reviewcrew.schemas import CodeEvidence, ContextPack, DiffHunk, PRData
from reviewcrew.tool_activity import ToolActivityPublisher
from reviewcrew.tools.files import ToolAccessError, safe_read
from reviewcrew.tools.search import find_related_tests, search_code, search_project_docs
from reviewcrew.tools.semgrep import run_semgrep


async def build_context(
    pr: PRData,
    repo: Path,
    config: Config,
    *,
    activity: ToolActivityPublisher | None = None,
    semgrep_available: bool | None = None,
) -> list[ContextPack]:
    """按修改文件构建上下文，并遵守单 Pack 字符预算。"""

    docs_handle = _started(
        activity,
        tool_name="context.read_docs",
        target=repo.name,
    )
    try:
        docs = search_project_docs(repo)
    except Exception:
        if docs_handle is not None:
            docs_handle.fail("项目文档读取失败，已继续构建基础上下文")
        raise
    if docs_handle is not None:
        docs_handle.complete(f"读取 {len(docs)} 份项目文档", result_count=len(docs))

    semgrep_enabled = shutil.which("semgrep") is not None if semgrep_available is None else semgrep_available
    if not semgrep_enabled:
        signals = []
        if activity is not None:
            activity.degraded(
                actor="context_builder",
                actor_type="system",
                tool_name="static.semgrep",
                target=repo.name,
                summary="Semgrep 未安装，静态扫描已降级",
            )
    else:
        semgrep_handle = _started(
            activity,
            tool_name="static.semgrep",
            target=f"{len(pr.files)} 个修改文件",
        )
        try:
            signals = await run_semgrep(repo, [item.path for item in pr.files], timeout=60)
        except Exception:
            if semgrep_handle is not None:
                semgrep_handle.fail("Semgrep 执行失败，已继续使用其他证据")
            raise
        if semgrep_handle is not None:
            semgrep_handle.complete(f"获得 {len(signals)} 条静态信号", result_count=len(signals))

    packs: list[ContextPack] = []
    for changed_file in pr.files:
        context_id = f"ctx-{sha1(f'{pr.head_sha}:{changed_file.path}'.encode()).hexdigest()[:12]}"
        enclosing: list[CodeEvidence] = []
        notes: list[str] = []
        for hunk in changed_file.hunks:
            start = max(1, hunk.new_start - 40)
            end = max(start, hunk.new_start + max(hunk.new_count, 1) + 40)
            read_handle = _started(
                activity,
                tool_name="context.read_file",
                target=f"{changed_file.path}:{start}-{end}",
                context_id=context_id,
            )
            try:
                evidence = safe_read(repo, changed_file.path, start, end)
                enclosing.append(evidence)
            except ToolAccessError as error:
                if read_handle is not None:
                    read_handle.fail("文件范围读取失败，已记录降级说明")
                notes.append(f"无法读取修改文件上下文：{error}")
            except Exception:
                if read_handle is not None:
                    read_handle.fail("文件范围读取失败，已停止当前上下文构建")
                raise
            else:
                if read_handle is not None:
                    read_handle.complete(
                        f"读取第 {evidence.start_line} 至 {evidence.end_line} 行",
                        result_count=max(0, evidence.end_line - evidence.start_line + 1),
                    )

        tests_handle = _started(
            activity,
            tool_name="context.find_tests",
            target=changed_file.path,
            context_id=context_id,
        )
        try:
            related_tests = find_related_tests(repo, changed_file.path)
        except Exception:
            if tests_handle is not None:
                tests_handle.fail("相关测试检索失败，已停止当前上下文构建")
            raise
        if tests_handle is not None:
            tests_handle.complete(
                f"找到 {len(related_tests)} 个相关测试片段",
                result_count=len(related_tests),
            )
        related_code = _find_related_code(
            repo,
            changed_file.path,
            changed_file.hunks,
            activity=activity,
            context_id=context_id,
        )
        pack = ContextPack(
            id=context_id,
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


def _find_related_code(
    repo: Path,
    changed_path: str,
    hunks: list[DiffHunk],
    *,
    activity: ToolActivityPublisher | None = None,
    context_id: str | None = None,
) -> list[CodeEvidence]:
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
        search_handle = _started(
            activity,
            tool_name="context.search_symbol",
            target=symbol,
            context_id=context_id,
        )
        try:
            matches = search_code(repo, symbol, limit=20)
        except Exception:
            if search_handle is not None:
                search_handle.fail("符号引用检索失败，已停止当前上下文构建")
            raise
        if search_handle is not None:
            search_handle.complete(
                f"检查符号引用并获得 {len(matches)} 个匹配片段",
                result_count=len(matches),
            )
        for evidence in matches:
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


def _started(
    activity: ToolActivityPublisher | None,
    *,
    tool_name: str,
    target: str,
    context_id: str | None = None,
):
    """存在运行级发布器时，才为即将执行的真实动作建立活动句柄。"""

    if activity is None:
        return None
    return activity.started(
        actor="context_builder",
        actor_type="system",
        tool_name=tool_name,
        target=target,
        context_id=context_id,
    )


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
