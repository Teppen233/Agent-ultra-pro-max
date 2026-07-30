from __future__ import annotations

import ast
import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import cast

import tree_sitter_java
from pydantic import BaseModel
from tree_sitter import Language, Node, Parser, Query, QueryCursor
from tree_sitter_language_pack import SupportedLanguage, get_parser

LANGUAGE_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "python": (".py",),
    "javascript": (".js", ".jsx", ".mjs", ".cjs"),
    "typescript": (".ts", ".tsx"),
    "go": (".go",),
    "rust": (".rs",),
    "java": (".java",),
}
FUNCTION_TYPES = {
    "function_definition",
    "function_declaration",
    "method_definition",
    "method_declaration",
}
CALL_TYPES = {"call", "call_expression", "method_invocation"}
MAX_SOURCE_BYTES = 512_000
SymbolRow = tuple[str, str, int, int, str]
CallRow = tuple[str, str, str, int]
ReferenceRow = tuple[str, str, int, int]


def _parser_for(language: str) -> Parser:
    if language == "java":
        return Parser(Language(tree_sitter_java.language()))
    return get_parser(cast(SupportedLanguage, language))


class Location(BaseModel):
    file: str
    line: int
    column: int


class FuncNode(BaseModel):
    name: str
    location: Location
    signature: str


def _walk(node: Node) -> Iterator[Node]:
    cursor = node.walk()
    finished = False
    while not finished:
        current = cursor.node
        if current is None:
            break
        yield current
        if cursor.goto_first_child():
            continue
        while not cursor.goto_next_sibling():
            if not cursor.goto_parent():
                finished = True
                break


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _name_node(node: Node) -> Node | None:
    return (
        node.child_by_field_name("name")
        or node.child_by_field_name("declarator")
        or node.child_by_field_name("property")
    )


def _call_name(node: Node, source: bytes) -> str | None:
    target = node.child_by_field_name("function") or node.child_by_field_name("name")
    if target is None:
        return None
    value = _node_text(target, source).strip()
    return value.rsplit(".", 1)[-1] if value else None


def _python_call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _index_python(
    source: bytes, relative: str
) -> tuple[list[SymbolRow], list[CallRow], list[ReferenceRow]]:
    text = source.decode("utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [], [], []
    lines = text.splitlines()
    symbols: list[SymbolRow] = []
    calls: list[CallRow] = []
    references: list[ReferenceRow] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        signature = (
            lines[node.lineno - 1].strip()[:500]
            if node.lineno <= len(lines)
            else node.name
        )
        symbols.append((node.name, relative, node.lineno, node.col_offset, signature))
        for descendant in ast.walk(node):
            if not isinstance(descendant, ast.Call):
                continue
            callee = _python_call_name(descendant)
            if callee is None:
                continue
            calls.append((node.name, callee, relative, descendant.lineno))
            references.append(
                (callee, relative, descendant.lineno, descendant.col_offset)
            )
    return symbols, calls, references


def _index_java(
    source: bytes, relative: str
) -> tuple[list[SymbolRow], list[CallRow], list[ReferenceRow]]:
    language = Language(tree_sitter_java.language())
    parser = Parser(language)
    tree = parser.parse(source)
    query = Query(
        language,
        """
        (method_declaration name: (identifier) @method.name) @method
        (constructor_declaration name: (identifier) @method.name) @method
        (method_invocation name: (identifier) @call.name) @call
        """,
    )
    cursor = QueryCursor(query)
    matches = cursor.matches(tree.root_node)
    method_ranges: list[tuple[int, int, str]] = []
    symbols: list[SymbolRow] = []
    pending_calls: list[tuple[int, str, int, int]] = []

    for pattern, captures in matches:
        if pattern in {0, 1}:
            method = captures["method"][0]
            name_node = captures["method.name"][0]
            name = _node_text(name_node, source)
            method_ranges.append((method.start_byte, method.end_byte, name))
            symbols.append(
                (
                    name,
                    relative,
                    name_node.start_point.row + 1,
                    name_node.start_point.column,
                    _node_text(method, source).splitlines()[0][:500],
                )
            )
            continue
        call = captures["call"][0]
        callee = _node_text(captures["call.name"][0], source)
        pending_calls.append(
            (call.start_byte, callee, call.start_point.row + 1, call.start_point.column)
        )

    calls: list[CallRow] = []
    references: list[ReferenceRow] = []
    for offset, callee, line, column in pending_calls:
        owner = min(
            (
                method
                for method in method_ranges
                if method[0] <= offset < method[1]
            ),
            key=lambda method: method[1] - method[0],
            default=None,
        )
        if owner is None:
            continue
        calls.append((owner[2], callee, relative, line))
        references.append((callee, relative, line, column))
    return symbols, calls, references


class RepoIndex:
    def __init__(self, db_path: Path, repo_path: Path | None = None) -> None:
        self.db_path = db_path
        self.repo_path = repo_path

    @classmethod
    def build(cls, repo_path: Path, langs: list[str]) -> RepoIndex:
        db_path = repo_path / "profile" / "symbols.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        index = cls(db_path, repo_path)
        index._initialize()
        with sqlite3.connect(db_path) as connection:
            connection.execute("DELETE FROM calls")
            connection.execute("DELETE FROM refs")
            connection.execute("DELETE FROM symbols")
        index._index_files(index._source_files(langs))
        return index

    @classmethod
    def build_selected(cls, repo_path: Path, changed_files: list[str]) -> RepoIndex:
        db_path = repo_path / "profile" / "symbols.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        index = cls(db_path, repo_path)
        index._initialize()
        by_extension = {
            extension: language
            for language, extensions in LANGUAGE_EXTENSIONS.items()
            for extension in extensions
        }
        files: list[tuple[Path, str]] = []
        for relative in changed_files:
            path = repo_path / relative
            language = by_extension.get(path.suffix)
            if path.is_file() and language and path.stat().st_size <= MAX_SOURCE_BYTES:
                files.append((path, language))
        index._index_files(files)
        return index

    def _initialize(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS symbols (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    file TEXT NOT NULL,
                    line INTEGER NOT NULL,
                    column_no INTEGER NOT NULL,
                    signature TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS symbols_name ON symbols(name);
                CREATE INDEX IF NOT EXISTS symbols_file ON symbols(file);
                CREATE TABLE IF NOT EXISTS refs (
                    symbol_name TEXT NOT NULL,
                    file TEXT NOT NULL,
                    line INTEGER NOT NULL,
                    column_no INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS refs_name ON refs(symbol_name);
                CREATE TABLE IF NOT EXISTS calls (
                    caller_name TEXT NOT NULL,
                    callee_name TEXT NOT NULL,
                    file TEXT NOT NULL,
                    line INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS calls_callee ON calls(callee_name);
                CREATE INDEX IF NOT EXISTS calls_caller ON calls(caller_name);
                """
            )

    def _source_files(self, langs: list[str]) -> list[tuple[Path, str]]:
        if self.repo_path is None:
            return []
        files: list[tuple[Path, str]] = []
        for language in langs:
            extensions = LANGUAGE_EXTENSIONS.get(language, ())
            for path in self.repo_path.rglob("*"):
                if (
                    path.is_file()
                    and path.suffix in extensions
                    and path.stat().st_size <= MAX_SOURCE_BYTES
                    and ".git" not in path.parts
                    and "profile" not in path.parts
                ):
                    files.append((path, language))
        return sorted(set(files))

    def _index_files(self, files: Iterable[tuple[Path, str]]) -> None:
        if self.repo_path is None:
            raise ValueError("repo_path is required to build or update an index")
        parsers: dict[str, Parser] = {}
        with sqlite3.connect(self.db_path) as connection:
            for path, language in files:
                source = path.read_bytes()
                relative = path.relative_to(self.repo_path).as_posix()
                if language == "python":
                    symbols, calls, references = _index_python(source, relative)
                    connection.executemany(
                        "INSERT INTO symbols(name, kind, file, line, column_no, signature) "
                        "VALUES (?, 'function', ?, ?, ?, ?)",
                        symbols,
                    )
                    connection.executemany(
                        "INSERT INTO calls(caller_name, callee_name, file, line) "
                        "VALUES (?, ?, ?, ?)",
                        calls,
                    )
                    connection.executemany(
                        "INSERT INTO refs(symbol_name, file, line, column_no) "
                        "VALUES (?, ?, ?, ?)",
                        references,
                    )
                    continue
                if language == "java":
                    symbols, calls, references = _index_java(source, relative)
                    connection.executemany(
                        "INSERT INTO symbols(name, kind, file, line, column_no, signature) "
                        "VALUES (?, 'function', ?, ?, ?, ?)",
                        symbols,
                    )
                    connection.executemany(
                        "INSERT INTO calls(caller_name, callee_name, file, line) "
                        "VALUES (?, ?, ?, ?)",
                        calls,
                    )
                    connection.executemany(
                        "INSERT INTO refs(symbol_name, file, line, column_no) "
                        "VALUES (?, ?, ?, ?)",
                        references,
                    )
                    continue
                if language not in parsers:
                    parsers[language] = _parser_for(language)
                parser = parsers[language]
                tree = parser.parse(source)
                root = tree.root_node
                symbols = []
                calls = []
                references = []
                for node in _walk(root):
                    if node.type in CALL_TYPES:
                        callee = _call_name(node, source)
                        owner = node.parent
                        while owner is not None and owner.type not in FUNCTION_TYPES:
                            owner = owner.parent
                        owner_name = _name_node(owner) if owner is not None else None
                        if not callee or owner_name is None:
                            continue
                        caller = _node_text(owner_name, source)
                        line = node.start_point.row + 1
                        calls.append((caller, callee, relative, line))
                        references.append(
                            (callee, relative, line, node.start_point.column)
                        )
                        continue
                    if node.type not in FUNCTION_TYPES:
                        continue
                    name_node = _name_node(node)
                    if name_node is None:
                        continue
                    name = _node_text(name_node, source)
                    signature = _node_text(node, source).splitlines()[0][:500]
                    symbols.append(
                        (
                            name,
                            relative,
                            node.start_point.row + 1,
                            node.start_point.column,
                            signature,
                        )
                    )
                connection.executemany(
                    "INSERT INTO symbols(name, kind, file, line, column_no, signature) "
                    "VALUES (?, 'function', ?, ?, ?, ?)",
                    symbols,
                )
                connection.executemany(
                    "INSERT INTO calls(caller_name, callee_name, file, line) "
                    "VALUES (?, ?, ?, ?)",
                    calls,
                )
                connection.executemany(
                    "INSERT INTO refs(symbol_name, file, line, column_no) "
                    "VALUES (?, ?, ?, ?)",
                    references,
                )

    def definition(self, symbol: str) -> Location | None:
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT file, line, column_no FROM symbols WHERE name = ? ORDER BY file LIMIT 1",
                (symbol,),
            ).fetchone()
        return Location(file=row[0], line=row[1], column=row[2]) if row else None

    def references(self, symbol: str) -> list[Location]:
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                "SELECT file, line, column_no FROM refs WHERE symbol_name = ? ORDER BY file, line",
                (symbol,),
            ).fetchall()
        return [Location(file=row[0], line=row[1], column=row[2]) for row in rows]

    def _functions(self, query: str, name: str, hops: int) -> list[FuncNode]:
        frontier = {name}
        visited = {name}
        discovered: list[str] = []
        with sqlite3.connect(self.db_path) as connection:
            for _ in range(hops):
                next_frontier: set[str] = set()
                for item in frontier:
                    rows = connection.execute(query, (item,)).fetchall()
                    for row in rows:
                        candidate = str(row[0])
                        if candidate not in visited:
                            visited.add(candidate)
                            discovered.append(candidate)
                            next_frontier.add(candidate)
                frontier = next_frontier
            output: list[FuncNode] = []
            for function_name in discovered:
                row = connection.execute(
                    "SELECT file, line, column_no, signature FROM symbols "
                    "WHERE name = ? ORDER BY file LIMIT 1",
                    (function_name,),
                ).fetchone()
                if row:
                    output.append(
                        FuncNode(
                            name=function_name,
                            location=Location(file=row[0], line=row[1], column=row[2]),
                            signature=row[3],
                        )
                    )
        return output

    def callers(self, func: str, hops: int = 1) -> list[FuncNode]:
        return self._functions(
            "SELECT DISTINCT caller_name FROM calls WHERE callee_name = ?", func, hops
        )

    def callees(self, func: str, hops: int = 1) -> list[FuncNode]:
        return self._functions(
            "SELECT DISTINCT callee_name FROM calls WHERE caller_name = ?", func, hops
        )

    def update_incremental(self, changed_files: list[str]) -> None:
        if self.repo_path is None:
            raise ValueError("repo_path is required for incremental updates")
        with sqlite3.connect(self.db_path) as connection:
            for relative in changed_files:
                connection.execute("DELETE FROM symbols WHERE file = ?", (relative,))
                connection.execute("DELETE FROM refs WHERE file = ?", (relative,))
                connection.execute("DELETE FROM calls WHERE file = ?", (relative,))
        by_extension = {
            extension: language
            for language, extensions in LANGUAGE_EXTENSIONS.items()
            for extension in extensions
        }
        files = []
        for relative in changed_files:
            path = self.repo_path / relative
            language = by_extension.get(path.suffix)
            if path.is_file() and language and path.stat().st_size <= MAX_SOURCE_BYTES:
                files.append((path, language))
        self._index_files(files)


def detect_languages(repo_path: Path) -> list[str]:
    detected = []
    for language, extensions in LANGUAGE_EXTENSIONS.items():
        if any(path.suffix in extensions for path in repo_path.rglob("*") if path.is_file()):
            detected.append(language)
    return detected
