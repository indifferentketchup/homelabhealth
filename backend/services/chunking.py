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


_LAB_UNITS = r'(%|mg/dL|U/mL|g/dL|g/L|mEq/L|mmol/L|IU/mL|ng/mL|pg/mL|mcg/dL|cells/mcL|K/uL|M/uL|fL|pg|g/dL|thou/uL|mill/uL|mL/min)'


def _parse_lab_text(text: str) -> str:
    """Parse text-extracted lab report: detect 'Value Range Units' header
    and reformat following data rows as explicit key-value pairs."""
    import re
    lines = text.split("\n")
    out: list[str] = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if re.match(r'^Value\s+Range\s+Units?\s*$', stripped, re.IGNORECASE):
            in_table = True
            continue
        if in_table:
            m = re.match(
                r'^(.+?)\s+(\S+)\s+(\S+)\s+' + _LAB_UNITS + r'\s*$',
                stripped,
            )
            if m and re.search(r'\d', m.group(2)):
                test, value, ref_range, units = m.groups()
                out.append(f"TEST: {test.strip()}")
                out.append(f"  Patient Value: {value} {units}")
                out.append(f"  Reference Range: {ref_range} {units}")
                continue
            else:
                in_table = False
        out.append(line)
    return "\n".join(out)


def _format_table_as_lab(table: list[list]) -> str | None:
    """If this table has Value/Range/Units columns, format each row as
    explicit key-value pairs. Returns None if not a lab-result table."""
    if not table or len(table) < 2:
        return None
    header = [str(c or "").strip().lower() for c in table[0]]
    val_idx = next((i for i, h in enumerate(header) if h == "value"), None)
    range_idx = next((i for i, h in enumerate(header) if h == "range"), None)
    units_idx = next((i for i, h in enumerate(header) if h in ("units", "unit")), None)
    if val_idx is None:
        return None
    lines: list[str] = []
    for row in table[1:]:
        cells = [str(c or "").strip() for c in row]
        if not any(cells):
            continue
        test_parts = [cells[i] for i in range(len(cells))
                      if i not in (val_idx, range_idx, units_idx) and cells[i]]
        test_name = " ".join(test_parts).strip()
        value = cells[val_idx] if val_idx < len(cells) else ""
        ref_range = cells[range_idx] if range_idx is not None and range_idx < len(cells) else ""
        units = cells[units_idx] if units_idx is not None and units_idx < len(cells) else ""
        if not value and not test_name:
            continue
        lines.append(f"TEST: {test_name}")
        lines.append(f"  Patient Value: {value} {units}".rstrip())
        if ref_range:
            lines.append(f"  Reference Range: {ref_range} {units}".rstrip())
    return "\n".join(lines) if lines else None


def parse_pdf(file_bytes: bytes) -> str:
    try:
        import pdfplumber

        parts: list[str] = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages):
                parts.append(f"\n[Page {page_num + 1}]\n")
                tables = page.extract_tables() or []
                has_lab_table = False
                for table in tables:
                    formatted = _format_table_as_lab(table)
                    if formatted:
                        parts.append(formatted)
                        has_lab_table = True
                    else:
                        for row in table:
                            cells = [str(c or "").strip() for c in row]
                            parts.append("  |  ".join(cells))
                        parts.append("")
                text = page.extract_text() or ""
                if text.strip():
                    if has_lab_table:
                        import re
                        filtered = []
                        for line in text.split("\n"):
                            s = line.strip()
                            if re.match(r'^Value\s+Range\s+Units?\s*$', s, re.IGNORECASE):
                                continue
                            if re.match(r'^.+\s+\d[\d.]*\s+[\d<>].*\s+(mg/dL|%|U/mL|g/dL|mEq/L|mmol/L|IU/mL|ng/mL|pg/mL|mcg/dL|cells/mcL)\s*$', s):
                                continue
                            filtered.append(line)
                        remainder = "\n".join(filtered).strip()
                        if remainder:
                            parts.append(remainder)
                    else:
                        parts.append(_parse_lab_text(text))
        return "\n".join(parts)
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
