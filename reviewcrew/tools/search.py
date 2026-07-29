"""提供有界代码、测试和项目文档搜索。"""

from __future__ import annotations

from pathlib import Path

from reviewcrew.schemas import CodeEvidence, TextEvidence
from reviewcrew.tools.files import safe_read


_SKIPPED_DIRS = {".git", ".idea", ".venv", "node_modules", "dist", "build", "runs"}
_TEXT_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".vue", ".go", ".java",
    ".rb", ".rs", ".c", ".h", ".cpp", ".hpp", ".yaml", ".yml", ".json",
    ".toml", ".md", ".txt",
}


def search_code(repo: Path, query: str, limit: int = 20) -> list[CodeEvidence]:
    """在仓库文本文件中搜索字符串并返回匹配行周边。"""

    if not query.strip() or limit < 1:
        return []
    results: list[CodeEvidence] = []
    for path in _iter_text_files(Path(repo)):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for number, line in enumerate(lines, start=1):
            if query in line:
                relative = path.relative_to(Path(repo).resolve()).as_posix()
                results.append(safe_read(repo, relative, max(1, number - 2), min(len(lines), number + 2)))
                if len(results) >= limit:
                    return results
    return results


def find_related_tests(repo: Path, changed_path: str, limit: int = 10) -> list[CodeEvidence]:
    """根据修改文件名查找可能相关的测试文件。"""

    stem = Path(changed_path).stem.removeprefix("test_").removesuffix("_test")
    candidates: list[Path] = []
    for path in _iter_text_files(Path(repo)):
        normalized = path.relative_to(Path(repo).resolve()).as_posix().lower()
        if "test" in normalized and stem.lower() in path.stem.lower():
            candidates.append(path)
    evidence: list[CodeEvidence] = []
    for path in candidates[:limit]:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if lines:
            relative = path.relative_to(Path(repo).resolve()).as_posix()
            evidence.append(safe_read(repo, relative, 1, min(120, len(lines))))
    return evidence


def search_project_docs(repo: Path, limit: int = 10) -> list[TextEvidence]:
    """读取与项目规范最相关的 Markdown 文档。"""

    names = {"readme.md", "contributing.md", "architecture.md", "security.md", "agents.md"}
    results: list[TextEvidence] = []
    for path in _iter_text_files(Path(repo)):
        if path.name.lower() not in names:
            continue
        content = path.read_text(encoding="utf-8", errors="replace")[:8_000]
        results.append(
            TextEvidence(
                source="project_docs",
                title=path.relative_to(Path(repo).resolve()).as_posix(),
                content=content,
                reference=path.as_posix(),
            )
        )
        if len(results) >= limit:
            break
    return results


def _iter_text_files(repo: Path):
    """按稳定顺序遍历可读取文本文件。"""

    root = repo.resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        if any(part in _SKIPPED_DIRS for part in path.relative_to(root).parts):
            continue
        yield path
