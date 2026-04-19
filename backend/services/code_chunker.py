"""Tree-sitter code-aware chunker for BooCode repo ingest.

Chunks top-level functions, classes, methods into their own records with line
ranges + symbol metadata. Falls back to sliding window for unknown file types.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 512 * 1024
MAX_CHUNK_CHARS = 8000  # ~2000 tokens at 4 chars/token
FALLBACK_WINDOW_CHARS = 800
FALLBACK_OVERLAP_CHARS = 100
OVERSIZE_OVERLAP_CHARS = 400

IGNORED_DIRS: frozenset[str] = frozenset({
    "node_modules", ".git", "dist", "build", "__pycache__",
    ".venv", "venv", "target", ".next", ".nuxt", ".cache",
    ".tox", "coverage", "vendor",
})

IGNORED_BINARY_EXTS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
    ".exe", ".dll", ".so", ".dylib", ".bin",
    ".pyc", ".pyo", ".class", ".o", ".obj",
})

IGNORED_NAMES: frozenset[str] = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Cargo.lock", "poetry.lock", "composer.lock",
    ".DS_Store", "Thumbs.db", "desktop.ini",
})

EXTENSION_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "tsx",  # tsx grammar handles JSX well
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".sql": "sql",
    ".md": "markdown",
    ".markdown": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
}

_AST_LANGUAGES: frozenset[str] = frozenset({
    "python", "javascript", "typescript", "tsx", "go", "rust", "bash", "sql",
})

# Per-language node-type classification for top-level and class-body walks.
# Keys: node.type → ('top' or 'method', symbol_kind).
_LANG_NODE_MAP: dict[str, dict[str, tuple[str, str]]] = {
    "python": {
        "function_definition": ("top_fn", "function"),
        "decorated_definition": ("top_fn", "function"),
        "class_definition": ("top_class", "class"),
        "async_function_definition": ("top_fn", "function"),
    },
    "javascript": {
        "function_declaration": ("top_fn", "function"),
        "generator_function_declaration": ("top_fn", "function"),
        "class_declaration": ("top_class", "class"),
        "method_definition": ("method", "method"),
        "export_statement": ("export", "export"),
        "lexical_declaration": ("prelude", "const"),
        "variable_declaration": ("prelude", "const"),
    },
    "typescript": {
        "function_declaration": ("top_fn", "function"),
        "generator_function_declaration": ("top_fn", "function"),
        "class_declaration": ("top_class", "class"),
        "interface_declaration": ("top_class", "interface"),
        "type_alias_declaration": ("top_fn", "type"),
        "method_definition": ("method", "method"),
        "method_signature": ("method", "method"),
        "export_statement": ("export", "export"),
        "lexical_declaration": ("prelude", "const"),
        "variable_declaration": ("prelude", "const"),
    },
    "tsx": {
        "function_declaration": ("top_fn", "function"),
        "generator_function_declaration": ("top_fn", "function"),
        "class_declaration": ("top_class", "class"),
        "interface_declaration": ("top_class", "interface"),
        "type_alias_declaration": ("top_fn", "type"),
        "method_definition": ("method", "method"),
        "method_signature": ("method", "method"),
        "export_statement": ("export", "export"),
        "lexical_declaration": ("prelude", "const"),
        "variable_declaration": ("prelude", "const"),
    },
    "go": {
        "function_declaration": ("top_fn", "function"),
        "method_declaration": ("top_fn", "method"),
        "type_declaration": ("top_class", "type"),
    },
    "rust": {
        "function_item": ("top_fn", "function"),
        "impl_item": ("top_class", "impl"),
        "struct_item": ("top_class", "struct"),
        "trait_item": ("top_class", "trait"),
        "enum_item": ("top_class", "enum"),
        "mod_item": ("top_class", "module"),
    },
    "bash": {
        "function_definition": ("top_fn", "function"),
    },
    "sql": {
        "create_function_statement": ("top_fn", "function"),
        "create_procedure_statement": ("top_fn", "procedure"),
        "create_table_statement": ("top_class", "table"),
        "create_view_statement": ("top_class", "view"),
    },
}


def _get_parser(language: str):
    """Lazy import tree-sitter parser; cached by language string."""
    try:
        from tree_sitter_languages import get_parser  # type: ignore[import-not-found]
    except Exception as e:
        logger.warning("tree_sitter_languages not available: %s", e)
        return None
    try:
        return get_parser(language)
    except Exception as e:
        logger.warning("tree-sitter parser unavailable for %s: %s", language, e)
        return None


def is_ignored_path(path: str) -> bool:
    """Return True if the path should be skipped before fetch."""
    lower = path.lower()
    parts = [p for p in lower.replace("\\", "/").split("/") if p]
    for part in parts[:-1]:
        if part in IGNORED_DIRS:
            return True
    if not parts:
        return False
    name = parts[-1]
    if name in IGNORED_NAMES:
        return True
    # Dockerfile special-case: no extension
    if name == "dockerfile" or name.startswith("dockerfile.") or name.endswith(".dockerfile"):
        return False
    ext = ""
    if "." in name:
        ext = "." + name.rsplit(".", 1)[-1]
    if ext and ext in IGNORED_BINARY_EXTS:
        return True
    return False


def resolve_language(path: str) -> str | None:
    """Map path → tree-sitter language id (or 'markdown'/'yaml'/'dockerfile'). None for fallback."""
    name = path.rsplit("/", 1)[-1].lower()
    if name == "dockerfile" or name.startswith("dockerfile.") or name.endswith(".dockerfile"):
        return "dockerfile"
    if "." not in name:
        return None
    ext = "." + name.rsplit(".", 1)[-1]
    return EXTENSION_TO_LANG.get(ext)


def estimate_tokens(text: str) -> int:
    """Cheap token estimator: len(text) // 4 (approximates OpenAI BPE behavior)."""
    return max(1, len(text) // 4)


def _slice(content_bytes: bytes, start: int, end: int) -> str:
    return content_bytes[start:end].decode("utf-8", errors="replace")


def _node_name(node, content_bytes: bytes) -> str | None:
    """Best-effort symbol name extraction via named children."""
    for child in node.children:
        if getattr(child, "type", None) == "identifier":
            return _slice(content_bytes, child.start_byte, child.end_byte)
    # Try named field 'name' (tree-sitter queries use field names)
    for field in ("name",):
        try:
            n = node.child_by_field_name(field)
            if n is not None:
                return _slice(content_bytes, n.start_byte, n.end_byte)
        except Exception:
            pass
    # Nested search (e.g. method_definition → property_identifier)
    for child in node.children:
        ct = getattr(child, "type", "")
        if ct in ("property_identifier", "field_identifier", "type_identifier"):
            return _slice(content_bytes, child.start_byte, child.end_byte)
    return None


def _split_oversize(
    content: str,
    start_line: int,
    end_line: int,
    symbol_kind: str,
    symbol_name: str | None,
    start_index: int,
) -> list[dict[str, Any]]:
    """Split a content block that exceeds MAX_CHUNK_CHARS into sliding windows.

    Line ranges are approximated: start_line for the first window, end_line for
    the last window, and linear interpolation in between. Not precise but good
    enough for UI display.
    """
    if len(content) <= MAX_CHUNK_CHARS:
        return [{
            "chunk_index": start_index,
            "symbol_kind": symbol_kind,
            "symbol_name": symbol_name,
            "start_line": start_line,
            "end_line": end_line,
            "content": content,
            "tokens": estimate_tokens(content),
        }]

    step = MAX_CHUNK_CHARS - OVERSIZE_OVERLAP_CHARS
    total_lines = max(1, end_line - start_line + 1)
    windows: list[dict[str, Any]] = []
    idx = start_index
    pos = 0
    while pos < len(content):
        piece = content[pos : pos + MAX_CHUNK_CHARS]
        if not piece:
            break
        ratio_start = pos / len(content)
        ratio_end = min(1.0, (pos + len(piece)) / len(content))
        sl = int(start_line + ratio_start * total_lines)
        el = max(sl, int(start_line + ratio_end * total_lines) - 1)
        windows.append({
            "chunk_index": idx,
            "symbol_kind": f"{symbol_kind}_part",
            "symbol_name": symbol_name,
            "start_line": sl,
            "end_line": el,
            "content": piece,
            "tokens": estimate_tokens(piece),
        })
        idx += 1
        pos += step
    return windows


def _chunk_ast(content: str, language: str) -> list[dict[str, Any]] | None:
    """Parse with tree-sitter and emit chunks. Returns None if parser unavailable."""
    parser = _get_parser(language)
    if parser is None:
        return None
    node_map = _LANG_NODE_MAP.get(language, {})
    content_bytes = content.encode("utf-8", errors="replace")
    try:
        tree = parser.parse(content_bytes)
    except Exception as e:
        logger.warning("tree-sitter parse failed (%s): %s", language, e)
        return None

    root = tree.root_node
    prelude_pieces: list[tuple[int, int, int, int]] = []  # (start_byte, end_byte, start_line, end_line)
    ast_chunks: list[dict[str, Any]] = []
    idx = 1  # chunk 0 reserved for prelude

    def _emit(node, kind: str, name: str | None, parent_name: str | None = None) -> None:
        nonlocal idx
        piece = _slice(content_bytes, node.start_byte, node.end_byte)
        if not piece.strip():
            return
        label = name or ""
        if parent_name and name:
            label = f"{parent_name}.{name}"
        elif parent_name and not name:
            label = parent_name
        sl = node.start_point[0] + 1
        el = node.end_point[0] + 1
        split = _split_oversize(piece, sl, el, kind, label or None, idx)
        ast_chunks.extend(split)
        idx = split[-1]["chunk_index"] + 1

    def _walk_class(node, class_name: str | None) -> None:
        body = None
        for child in node.children:
            ct = getattr(child, "type", "")
            if ct in ("block", "class_body", "declaration_list", "field_declaration_list"):
                body = child
                break
        if body is None:
            return
        for child in body.children:
            ct = getattr(child, "type", "")
            info = node_map.get(ct)
            if info is None:
                continue
            role, kind = info
            if role == "method":
                name = _node_name(child, content_bytes)
                _emit(child, kind, name, parent_name=class_name)

    for child in root.children:
        ct = getattr(child, "type", "")
        info = node_map.get(ct)
        if info is None:
            # Non-definition top-level → prelude
            prelude_pieces.append(
                (child.start_byte, child.end_byte, child.start_point[0] + 1, child.end_point[0] + 1)
            )
            continue
        role, kind = info
        if role == "top_fn":
            name = _node_name(child, content_bytes)
            _emit(child, kind, name)
        elif role == "top_class":
            name = _node_name(child, content_bytes)
            # Class header chunk: just the "class Foo:" line + docstring-ish opening portion.
            # Easiest: emit the whole class as one chunk, plus per-method chunks.
            header_end = child.start_byte
            # Include leading signature up to first body child if possible.
            body_node = None
            for inner in child.children:
                if getattr(inner, "type", "") in (
                    "block", "class_body", "declaration_list", "field_declaration_list"
                ):
                    body_node = inner
                    break
            if body_node is not None:
                # Header = class sig + statements in body up to first method.
                first_method_start = None
                for inner in body_node.children:
                    ict = getattr(inner, "type", "")
                    sub = node_map.get(ict)
                    if sub and sub[0] == "method":
                        first_method_start = inner.start_byte
                        break
                header_end = first_method_start if first_method_start is not None else child.end_byte
            else:
                header_end = child.end_byte
            header_piece = _slice(content_bytes, child.start_byte, header_end).rstrip()
            if header_piece.strip():
                sl = child.start_point[0] + 1
                # approximate end_line for header
                el = sl + header_piece.count("\n")
                split = _split_oversize(header_piece, sl, el, kind, name, idx)
                ast_chunks.extend(split)
                idx = split[-1]["chunk_index"] + 1
            # Walk methods
            _walk_class(child, name)
        elif role == "prelude" or role == "export":
            # export / top-level const declarations bundle with prelude
            prelude_pieces.append(
                (child.start_byte, child.end_byte, child.start_point[0] + 1, child.end_point[0] + 1)
            )

    # Assemble prelude as chunk 0 if any content
    final_chunks: list[dict[str, Any]] = []
    if prelude_pieces:
        prelude_pieces.sort(key=lambda p: p[0])
        combined = "\n".join(
            _slice(content_bytes, s, e).strip("\n") for (s, e, _sl, _el) in prelude_pieces
        )
        if combined.strip():
            sl = prelude_pieces[0][2]
            el = prelude_pieces[-1][3]
            final_chunks.extend(_split_oversize(combined, sl, el, "prelude", None, 0))

    final_chunks.extend(ast_chunks)
    # Renumber chunk_index to be contiguous from 0 (prelude may have occupied 0 or split)
    for i, ch in enumerate(final_chunks):
        ch["chunk_index"] = i

    if not final_chunks:
        # Parser succeeded but emitted nothing → single whole-file chunk
        return _chunk_whole(content, symbol_kind="prose")
    return final_chunks


def _chunk_markdown(content: str) -> list[dict[str, Any]]:
    """Split markdown by H1/H2 headings. Preserves heading line in chunk."""
    lines = content.split("\n")
    if not lines:
        return []

    sections: list[tuple[int, int, str, str]] = []  # (start_line, end_line, heading, body)
    cur_start = 1
    cur_heading = ""
    cur_body: list[str] = []

    def _flush(end_line: int) -> None:
        body_text = "\n".join(cur_body).rstrip()
        if body_text.strip() or cur_heading:
            sections.append((cur_start, end_line, cur_heading, body_text))

    for i, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        is_h12 = stripped.startswith("# ") or stripped.startswith("## ")
        if is_h12 and (cur_heading or cur_body):
            _flush(i - 1)
            cur_start = i
            cur_heading = line.strip()
            cur_body = [line]
        else:
            if not cur_heading and not cur_body:
                cur_start = i
                cur_heading = line.strip() if is_h12 else ""
            cur_body.append(line)
    _flush(len(lines))

    chunks: list[dict[str, Any]] = []
    idx = 0
    for sl, el, heading, body in sections:
        name = heading.lstrip("#").strip() if heading else None
        split = _split_oversize(body, sl, el, "heading", name, idx)
        chunks.extend(split)
        idx = split[-1]["chunk_index"] + 1
    for i, ch in enumerate(chunks):
        ch["chunk_index"] = i
    return chunks or _chunk_whole(content, symbol_kind="prose")


def _chunk_whole(content: str, symbol_kind: str = "prose") -> list[dict[str, Any]]:
    """Emit entire content as one chunk (split into sliding windows if oversized)."""
    sl = 1
    el = max(1, content.count("\n") + 1)
    return _split_oversize(content, sl, el, symbol_kind, None, 0)


def _chunk_fallback(content: str) -> list[dict[str, Any]]:
    """Sliding window for unknown/plaintext: 800 chars with 100 overlap."""
    if not content.strip():
        return []
    out: list[dict[str, Any]] = []
    step = FALLBACK_WINDOW_CHARS - FALLBACK_OVERLAP_CHARS
    pos = 0
    total_len = len(content)
    total_lines = max(1, content.count("\n") + 1)
    idx = 0
    while pos < total_len:
        piece = content[pos : pos + FALLBACK_WINDOW_CHARS]
        if not piece:
            break
        ratio_start = pos / total_len
        ratio_end = min(1.0, (pos + len(piece)) / total_len)
        sl = max(1, int(1 + ratio_start * total_lines))
        el = max(sl, int(1 + ratio_end * total_lines) - 1)
        out.append({
            "chunk_index": idx,
            "symbol_kind": "block",
            "symbol_name": None,
            "start_line": sl,
            "end_line": el,
            "content": piece,
            "tokens": estimate_tokens(piece),
        })
        idx += 1
        pos += step
    return out


def chunk_file(content: str, path: str) -> list[dict[str, Any]]:
    """Entry point: chunk file content by language heuristic.

    Returns a list of dicts with fields:
      chunk_index, symbol_kind, symbol_name, start_line, end_line, content, tokens.
    """
    if not content:
        return []
    language = resolve_language(path)
    if language == "markdown":
        chunks = _chunk_markdown(content)
    elif language in ("yaml", "dockerfile"):
        chunks = _chunk_whole(content, symbol_kind="config")
    elif language in _AST_LANGUAGES:
        chunks = _chunk_ast(content, language) or _chunk_fallback(content)
    else:
        chunks = _chunk_fallback(content)
    return chunks
