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


def _format_lab_tables(text: str) -> str:
    """Post-process extracted PDF text to clarify lab result tables.

    Detects common lab patterns where Value/Range/Units columns have
    been flattened into a single line and reformats them as explicit
    key-value pairs so the LLM can read them unambiguously.
    """
    import re
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Pattern: "Test Name  >100  >=68  %" or "Test Name  37  22-37  mg/dL"
        m = re.match(
            r'^(.+?)\s{2,}([<>]?\d[\d.]*)\s{2,}([<>]=?\d[\d.–-]*)\s{2,}(%|mg/dL|U/mL|g/dL|mEq/L|mmol/L|IU/mL|ng/mL|pg/mL|mcg/dL|cells/mcL)$',
            stripped,
        )
        if m:
            test, value, ref_range, units = m.groups()
            out.append(f"TEST: {test.strip()}")
            out.append(f"  Value: {value} {units}")
            out.append(f"  Reference Range: {ref_range} {units}")
            continue
        # Pattern: header row "Value  Range  Units" — skip (redundant after reformat)
        if re.match(r'^Value\s+Range\s+Units\s*$', stripped):
            continue
        out.append(line)
    return "\n".join(out)


def parse_pdf(file_bytes: bytes) -> str:
    try:
        import pdfplumber

        parts: list[str] = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages):
                parts.append(f"\n[Page {page_num + 1}]\n")
                # Extract tables separately for structure preservation
                tables = page.extract_tables() or []
                if tables:
                    for table in tables:
                        for row in table:
                            cells = [str(c or "").strip() for c in row]
                            parts.append("  |  ".join(cells))
                        parts.append("")
                # Also extract full text for non-table content
                text = page.extract_text() or ""
                if text.strip():
                    parts.append(text)
        raw = "\n".join(parts)
        return _format_lab_tables(raw)
    except ImportError:
        pass
    # Fallback to pypdf if pdfplumber not installed
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        parts = []
        for page_num, page in enumerate(reader.pages):
            parts.append(f"\n[Page {page_num + 1}]\n")
            parts.append(page.extract_text() or "")
        raw = "".join(parts)
        return _format_lab_tables(raw)
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


def parse_image(file_bytes: bytes) -> str:
    """OCR an image file using Tesseract. Returns extracted text."""
    try:
        from PIL import Image
        import pytesseract
        img = Image.open(io.BytesIO(file_bytes))
        text = pytesseract.image_to_string(img)
        if not text or not text.strip():
            raise ValueError("OCR produced no text — image may be blank or unreadable")
        return text.strip()
    except ImportError as e:
        raise ValueError(f"OCR dependencies not available: {e}") from e
    except Exception as e:
        raise ValueError(f"Image OCR failed: {e}") from e


def parse_source_bytes(file_bytes: bytes, mime_type: str) -> str:
    m = (mime_type or "").lower().split(";")[0].strip()
    if m in ("text/plain", "text/markdown", "text/x-markdown"):
        return parse_text(file_bytes)
    if m == "application/pdf":
        return parse_pdf(file_bytes)
    if m == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return parse_docx(file_bytes)
    if m.startswith("image/"):
        return parse_image(file_bytes)
    raise ValueError(f"Unsupported MIME type: {mime_type}")
