"""Vision extraction via MedGemma multimodal (hlh_chat with --mmproj).

Two-pass approach for medical images:
  Pass 1 — TEXT: extract any visible text (labels, overlays, report text)
  Pass 2 — IMAGE: interpret the medical image content (findings, anatomy)
  Consolidate: merge both into a structured output

For documents (PDFs rendered as pages), a single text-extraction pass
is used since the content is primarily textual.
"""

import base64
import logging
from io import BytesIO

import httpx

from services.provider_client import build_headers, resolve_bundled_chat_provider

logger = logging.getLogger(__name__)

VISION_TIMEOUT = 300.0
# The chat model preset (models.ini) — MedGemma is multimodal, so the same
# instance that serves chat also reads images once its mmproj is loaded. MUST be
# sent as the request "model" or the llama-server router 400s the call. Using the
# chat model (vs a separate vision preset) avoids a second model in VRAM.
VISION_MODEL = "medgemma"

TEXT_EXTRACTION_PROMPT = (
    "Extract all visible text from this image exactly as shown. "
    "Include headers, labels, overlays, patient information, dates, "
    "and any printed or handwritten text. "
    "For lab results, format as:\n"
    "TEST: <test name>\n"
    "  Patient Value: <value> <units>\n"
    "  Reference Range: <range> <units>\n"
    "If there is no readable text in the image, respond with: NO_TEXT_FOUND"
)

IMAGE_INTERPRETATION_PROMPT = (
    "You are analyzing a medical image. Describe your findings as a "
    "radiologist or clinician would, using structured format:\n\n"
    "MODALITY: <type of imaging — X-ray, ultrasound, CT, MRI, photo, etc.>\n"
    "REGION: <body region or organ system>\n"
    "FINDINGS:\n"
    "- <finding 1>\n"
    "- <finding 2>\n"
    "IMPRESSION: <brief overall assessment>\n\n"
    "Be specific about what you observe. Note normal findings as well as "
    "any abnormalities. If the image is not a medical scan (e.g., it is a "
    "photograph of a document), respond with: NOT_A_SCAN"
)

DOCUMENT_EXTRACTION_PROMPT = (
    "Extract all text from this medical document exactly as shown. "
    "For lab results, format each result as:\n"
    "TEST: <test name>\n"
    "  Patient Value: <value> <units>\n"
    "  Reference Range: <range> <units>\n"
    "Include all dates, patient names, locations, and identifiers exactly as they appear. "
    "Do not add any commentary or interpretation."
)


def is_vision_available() -> bool:
    """True when the active mmproj is present — the chat model loads it and can
    then read images. Gates every vision call so we don't ask the model to read
    an image when its projector isn't loaded."""
    from pathlib import Path
    import os
    models_base = Path(os.environ.get("HLH_MODELS_DIR", "/models"))
    return (models_base / "vision" / "active-mmproj.gguf").exists()


async def _call_vision(image_bytes: bytes, prompt: str, mime_type: str = "image/png") -> str | None:
    """Send an image + prompt to the bundled chat model. Returns response text or None."""
    binding = await resolve_bundled_chat_provider()
    if binding is None:
        logger.info("vision: no bundled chat provider available; skipping vision extraction")
        return None
    provider, _ = binding  # model is always medgemma for vision; ignore the alias

    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64}"

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }

    try:
        async with httpx.AsyncClient(timeout=VISION_TIMEOUT) as client:
            resp = await client.post(
                f"{provider.base_url}/v1/chat/completions",
                json=payload,
                headers=build_headers(provider),
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return content.strip() if content else None
    except Exception as exc:
        logger.warning("vision call failed: %s", exc)
        return None


async def extract_image_via_vision(image_bytes: bytes, mime_type: str) -> str | None:
    """Two-pass extraction for standalone images.

    Pass 1: extract any visible text (overlays, labels, report text)
    Pass 2: interpret the medical image content (findings, anatomy)
    Consolidate into a single output.
    """
    if not is_vision_available():
        return None

    text_result = await _call_vision(image_bytes, TEXT_EXTRACTION_PROMPT, mime_type)
    has_text = text_result and "NO_TEXT_FOUND" not in text_result

    interp_result = await _call_vision(image_bytes, IMAGE_INTERPRETATION_PROMPT, mime_type)
    is_scan = interp_result and "NOT_A_SCAN" not in interp_result

    parts: list[str] = []

    if has_text:
        parts.append("[TEXT FROM IMAGE]")
        parts.append(text_result)

    if is_scan:
        parts.append("")
        parts.append("[IMAGE INTERPRETATION]")
        parts.append(interp_result)

    if not parts:
        logger.warning("vision: both passes returned nothing for image")
        return None

    result = "\n".join(parts)
    logger.info("vision image extraction: text=%s, scan=%s, %d chars",
                "yes" if has_text else "no",
                "yes" if is_scan else "no",
                len(result))
    return result


async def extract_pdf_via_vision(file_bytes: bytes) -> str | None:
    """Render each PDF page as PNG and extract text via vision model.

    PDFs are treated as documents — single text-extraction pass per page.
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
        text = await _call_vision(buf.getvalue(), DOCUMENT_EXTRACTION_PROMPT, "image/png")
        if text:
            parts.append(f"\n[Page {i + 1}]\n")
            parts.append(text)
        else:
            logger.warning("vision extraction returned no text for page %d", i + 1)

    return "\n".join(parts) if parts else None
