"""Vision extraction via MedGemma multimodal (hlh_chat with --mmproj).

Sends page images to the hlh_chat sidecar's /v1/chat/completions endpoint
with base64-encoded image_url content. Used during source ingest for
structured text extraction from PDFs and images.
"""

import base64
import logging
from io import BytesIO

import httpx

logger = logging.getLogger(__name__)

VISION_URL = "http://hlh_chat:9610/v1/chat/completions"
VISION_TIMEOUT = 300.0  # seconds — vision inference is slow on CPU (~10 t/s + image encoding overhead)

EXTRACTION_PROMPT = (
    "Extract all text from this medical document exactly as shown. "
    "For lab results, format each result as:\n"
    "TEST: <test name>\n"
    "  Patient Value: <value> <units>\n"
    "  Reference Range: <range> <units>\n"
    "Include all dates, patient names, locations, and identifiers exactly as they appear. "
    "Do not add any commentary or interpretation."
)


def is_vision_available() -> bool:
    """Check if the active mmproj symlink exists on the shared models volume.

    This is a filesystem check, not a network probe. The symlink is managed
    by bundled_providers.link_active_mmproj() and only exists when the
    mmproj file has been pulled for the active tier. Checking the file
    (rather than hlh_chat /health) avoids the case where hlh_chat is
    running without --mmproj and would silently ignore image payloads.
    """
    from pathlib import Path
    import os
    models_base = Path(os.environ.get("HLH_MODELS_DIR", "/models"))
    return (models_base / "vision" / "active-mmproj.gguf").exists()


async def extract_via_vision(image_bytes: bytes, mime_type: str = "image/png") -> str | None:
    """Send an image to hlh_chat for vision-based text extraction.

    Returns extracted text, or None if vision is unavailable or fails.
    """
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64}"

    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACTION_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }

    try:
        async with httpx.AsyncClient(timeout=VISION_TIMEOUT) as client:
            resp = await client.post(VISION_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return content.strip() if content else None
    except Exception as exc:
        logger.warning("vision extraction failed: %s", exc)
        return None


async def extract_pdf_via_vision(file_bytes: bytes) -> str | None:
    """Render each PDF page as PNG and extract text via vision model.

    Returns concatenated text with [Page N] markers, or None if vision
    is unavailable or pdf2image is not installed.
    """
    try:
        from pdf2image import convert_from_bytes
    except ImportError:
        logger.info("pdf2image not installed; skipping vision extraction")
        return None

    if not is_vision_available():
        return None

    try:
        images = convert_from_bytes(file_bytes, dpi=150)
    except Exception as exc:
        logger.warning("pdf2image conversion failed: %s", exc)
        return None

    parts: list[str] = []
    for i, img in enumerate(images):
        buf = BytesIO()
        img.save(buf, format="PNG")
        text = await extract_via_vision(buf.getvalue(), "image/png")
        if text:
            parts.append(f"\n[Page {i + 1}]\n")
            parts.append(text)
        else:
            logger.warning("vision extraction returned no text for page %d", i + 1)

    return "\n".join(parts) if parts else None


async def extract_image_via_vision(file_bytes: bytes, mime_type: str) -> str | None:
    """Extract text from an image file via vision model."""
    if not is_vision_available():
        return None
    return await extract_via_vision(file_bytes, mime_type)
