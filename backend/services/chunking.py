"""Parse uploads and chunk text for RAG."""

from __future__ import annotations

import io
import os

from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "150"))

# Extension → LangChain Language enum. Anything not listed uses the generic splitter.
_LANGUAGE_BY_EXT: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".js": Language.JS,
    ".jsx": Language.JS,
    ".ts": Language.TS,
    ".tsx": Language.TS,
    ".go": Language.GO,
    ".java": Language.JAVA,
    ".rs": Language.RUST,
    ".rb": Language.RUBY,
    ".php": Language.PHP,
    ".md": Language.MARKDOWN,
    ".markdown": Language.MARKDOWN,
    ".html": Language.HTML,
    ".htm": Language.HTML,
    ".css": Language.HTML,  # not ideal but closer than generic
}


def _splitter_for(filename: str | None) -> RecursiveCharacterTextSplitter:
    ext = ""
    if filename:
        _, _, e = filename.rpartition(".")
        if e and e != filename:
            ext = "." + e.lower()
    lang = _LANGUAGE_BY_EXT.get(ext)
    if lang is not None:
        return RecursiveCharacterTextSplitter.from_language(
            language=lang,
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )


def chunk_text(text: str, filename: str | None = None) -> list[str]:
    return _splitter_for(filename).split_text(text)


def parse_pdf(file_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        parts: list[str] = []
        for page_num, page in enumerate(reader.pages):
            parts.append(f"\n[Page {page_num + 1}]\n")
            parts.append(page.extract_text() or "")
        return "".join(parts)
    except Exception as e:
        raise ValueError(f"PDF parse failed: {e}") from e


def parse_docx(file_bytes: bytes) -> str:
    try:
        from docx import Document

        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        raise ValueError(f"DOCX parse failed: {e}") from e


def parse_text(file_bytes: bytes) -> str:
    return file_bytes.decode("utf-8", errors="replace")


def parse_source_bytes(file_bytes: bytes, mime_type: str) -> str:
    m = (mime_type or "").lower().split(";")[0].strip()
    if m in ("text/plain", "text/markdown", "text/x-markdown"):
        return parse_text(file_bytes)
    if m == "application/pdf":
        return parse_pdf(file_bytes)
    if m == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return parse_docx(file_bytes)
    raise ValueError(f"Unsupported MIME type: {mime_type}")
