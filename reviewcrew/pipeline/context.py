from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import tiktoken
from pydantic import BaseModel

from reviewcrew.models import ContextPack, FileDiff, Signal
from reviewcrew.profile.builder import RepoProfile
from reviewcrew.profile.indexer import RepoIndex


class PRMeta(BaseModel):
    title: str = ""
    description: str = ""
    issue_links: list[str] = []
    test_changes: str = ""


def cluster_by_semantics(diffs: list[FileDiff]) -> list[list[FileDiff]]:
    groups: dict[str, list[FileDiff]] = defaultdict(list)
    for diff in diffs:
        parts = Path(diff.path).parts
        key = "/".join(parts[:2]) if len(parts) > 2 else (parts[0] if parts else "root")
        groups[key].append(diff)
    return list(groups.values())


def estimate_tokens(value: str) -> int:
    return len(tiktoken.get_encoding("cl100k_base").encode(value))


def trim_to_context_window(pack: ContextPack, max_tokens: int = 32_000) -> ContextPack:
    while estimate_tokens(pack.model_dump_json()) > max_tokens:
        candidates: list[tuple[int, str, str]] = []
        for kind in ("callers", "callees"):
            mapping = getattr(pack, kind)
            for symbol, snippets in mapping.items():
                if snippets:
                    candidates.append((len(snippets[-1]), kind, symbol))
        if candidates:
            _, kind, symbol = max(candidates)
            getattr(pack, kind)[symbol].pop()
            continue
        if pack.enclosing_code:
            path = max(pack.enclosing_code, key=lambda item: len(pack.enclosing_code[item]))
            content = pack.enclosing_code[path]
            if len(content) > 1000:
                pack.enclosing_code[path] = content[: len(content) // 2]
                continue
            del pack.enclosing_code[path]
            continue
        break
    return pack


def _intent(meta: PRMeta) -> str:
    issues = "\n".join(meta.issue_links) or "None"
    return (
        f"PR title: {meta.title}\n"
        f"Description: {meta.description}\n"
        f"Issues:\n{issues}\n"
        f"Test changes: {meta.test_changes}"
    )


def _code(repo_path: Path, relative: str, max_chars: int = 16_000) -> str:
    path = repo_path / relative
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:max_chars]


def build_context_packs(
    diffs: list[FileDiff],
    index: RepoIndex,
    profile: RepoProfile,
    signals: list[Signal],
    pr_meta: PRMeta,
) -> list[ContextPack]:
    packs: list[ContextPack] = []
    bug_patterns = profile.bug_patterns_path.read_text(encoding="utf-8", errors="replace")
    for sequence, group in enumerate(cluster_by_semantics(diffs), 1):
        paths = [diff.path for diff in group]
        prefix_parts = Path(paths[0]).parts
        pack_id = prefix_parts[1] if len(prefix_parts) > 2 else Path(paths[0]).stem
        if any(pack.pack_id == pack_id for pack in packs):
            pack_id = f"{pack_id}-{sequence}"
        callers: dict[str, list[str]] = {}
        callees: dict[str, list[str]] = {}
        symbols = {
            token
            for diff in group
            for hunk in diff.hunks
            for line in hunk.lines
            for token in line.replace("(", " ").replace(".", " ").split()
            if token.isidentifier() and index.definition(token) is not None
        }
        for symbol in symbols:
            callers[symbol] = [node.signature for node in index.callers(symbol, hops=2)]
            callees[symbol] = [node.signature for node in index.callees(symbol, hops=2)]
        pack = ContextPack(
            pack_id=pack_id,
            diff_hunks=group,
            enclosing_code={path: _code(profile.repo_path, path) for path in paths},
            callers=callers,
            callees=callees,
            arch_summary=profile.arch_slice(paths),
            bug_patterns=bug_patterns[:4096],
            intent=_intent(pr_meta),
            static_signals=[signal for signal in signals if signal.file in paths],
        )
        packs.append(trim_to_context_window(pack))
    return packs
