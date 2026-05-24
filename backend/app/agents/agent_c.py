"""
Agent C — Multimodal Extraction (VLM).

Uses Claude Vision (claude-sonnet-4-20250514) to extract structured data from:
  - Vehicle damage photos  → {parts_damaged, severity, estimated_repair_RD}
  - Workshop quotes (PDF/image) → {items, total, taller_name, date}
  - Police report scans   → {incident_date, location, parties, description, acta_number}

In PoC mode (no real image bytes available), the agent operates on the text
description stored in extracted_data["file_url"] / doc_type and returns a
plausible structured extraction for demonstration purposes.
"""
from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

from anthropic import AsyncAnthropic

if TYPE_CHECKING:
    from app.agents.orchestrator import ClaimState

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
VLM_MODEL = "claude-sonnet-4-6"

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _client


# ── Extraction prompts per document type ──────────────────────────────────────

_PROMPTS: dict[str, str] = {
    "fotos_danos": (
        "You are a vehicle damage assessment expert for an insurance company. "
        "Analyse the vehicle damage shown and return ONLY valid JSON with keys: "
        "parts_damaged (list of strings), severity (minor|moderate|severe|total_loss), "
        "estimated_repair_RD (integer in Dominican pesos). "
        "If this is a text description rather than an image, infer from the text."
    ),
    "cotizacion_taller": (
        "You are an insurance document analyst. Extract the workshop quote details and "
        "return ONLY valid JSON with keys: taller_name (string), date (ISO date string), "
        "items (list of {description, quantity, unit_price_RD}), total_RD (integer)."
    ),
    "acta_policial": (
        "You are a legal document analyst for an insurance company. "
        "Extract the police report details and return ONLY valid JSON with keys: "
        "acta_number (string), incident_date (ISO date), incident_time (HH:MM), "
        "location (string), parties (list of {name, role, cedula}), "
        "description (string), officer_badge (string)."
    ),
}

_DEFAULT_PROMPT = (
    "You are an insurance document analyst. Extract relevant structured data from "
    "the provided document or description and return ONLY valid JSON."
)

# ── Validation prompts per document type ──────────────────────────────────────

_VALIDATION_PROMPTS: dict[str, str] = {
    "fotos_danos": (
        "You are a vehicle insurance expert. Look at this image and determine if it shows "
        "visible vehicle damage suitable for an insurance claim. "
        "Return ONLY valid JSON with keys: "
        "valid (boolean), reason (string explaining the result), "
        "damage_visible (boolean), vehicle_present (boolean)."
    ),
    "fotos_danos_con_placa": (
        "You are a vehicle insurance expert. Determine if this image shows a damaged vehicle "
        "with a clearly visible license plate. "
        "Return ONLY valid JSON with keys: "
        "valid (boolean), reason (string), plate_visible (boolean), damage_visible (boolean)."
    ),
    "acta_policial": (
        "You are a document verification specialist. Determine if this document is a police report "
        "(acta policial) with an official header, case number, date, and officer signature. "
        "Return ONLY valid JSON with keys: "
        "valid (boolean), reason (string), has_case_number (boolean), has_date (boolean), has_signature (boolean)."
    ),
    "acta_policial_certificada": (
        "Determine if this is a certified police report with official stamps/seals. "
        "Return ONLY valid JSON: valid (boolean), reason (string), has_seal (boolean)."
    ),
    "cedula": (
        "Determine if this image shows a Dominican Republic national ID (cédula de identidad). "
        "Return ONLY valid JSON: valid (boolean), reason (string), name_visible (boolean), id_number_visible (boolean)."
    ),
    "licencia_conducir": (
        "Determine if this image shows a valid driver's license. "
        "Return ONLY valid JSON: valid (boolean), reason (string), name_visible (boolean), expiry_visible (boolean)."
    ),
    "cotizacion_taller": (
        "Determine if this document is a workshop repair quote with itemized costs and a total. "
        "Return ONLY valid JSON: valid (boolean), reason (string), has_total (boolean), has_items (boolean), taller_name (string)."
    ),
    "matricula": (
        "Determine if this image shows a vehicle registration document (matrícula). "
        "Return ONLY valid JSON: valid (boolean), reason (string), plate_number_visible (boolean)."
    ),
    "denuncia_policial": (
        "Determine if this is an official police complaint/report document. "
        "Return ONLY valid JSON: valid (boolean), reason (string), has_case_number (boolean)."
    ),
}

_DEFAULT_VALIDATION_PROMPT = (
    "Determine if this image or document is a valid, legible official document suitable "
    "for an insurance claim. Return ONLY valid JSON: valid (boolean), reason (string)."
)


def _build_content(file_url: str, fallback_text: str) -> list[dict]:
    """Build Claude Vision message content from data URI or fallback to text."""
    if file_url and file_url.startswith("data:"):
        header, b64data = file_url.split(",", 1)
        media_type = header.split(":")[1].split(";")[0]
        return [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64data},
            },
            {"type": "text", "text": "Analyse this document as instructed."},
        ]
    if file_url and file_url.startswith("http"):
        return [
            {"type": "image", "source": {"type": "url", "url": file_url}},
            {"type": "text", "text": "Analyse this document as instructed."},
        ]
    return [{"type": "text", "text": fallback_text}]


async def validate_document(
    doc_key: str,
    file_url: str,
    claim_id: str = "UNKNOWN",
) -> dict:
    """
    Validate a single uploaded document using Claude Vision.

    Returns:
        {
            "valid": bool,
            "reason": str,
            "doc_key": str,
            "skipped": bool   # True when no API key available
        }
    """
    if not ANTHROPIC_API_KEY:
        return {
            "valid": True,
            "reason": "Validación omitida — API key no configurada",
            "doc_key": doc_key,
            "skipped": True,
        }

    system_prompt = _VALIDATION_PROMPTS.get(doc_key, _DEFAULT_VALIDATION_PROMPT)
    content = _build_content(
        file_url,
        fallback_text=f"Document type expected: {doc_key}. No image available.",
    )

    try:
        client = _get_client()
        response = await client.messages.create(
            model=VLM_MODEL,
            max_tokens=256,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": content}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        result.setdefault("valid", False)
        result.setdefault("reason", "Sin respuesta del modelo")
        result["doc_key"] = doc_key
        result["skipped"] = False
        logger.info("[Agent C] Validated %s for %s: valid=%s", doc_key, claim_id, result["valid"])
        return result
    except Exception as exc:
        logger.warning("[Agent C] Validation failed for %s/%s: %s", doc_key, claim_id, exc)
        return {
            "valid": False,
            "reason": f"Error al validar el documento: {exc}",
            "doc_key": doc_key,
            "skipped": False,
        }


async def extract_from_document(state: "ClaimState") -> dict:
    """
    Extract structured data from a document image/description via Claude Vision.

    Reads from state["extracted_data"]:
        file_url    str  — URL or base64 data URI of the document
        doc_type    str  — one of: fotos_danos, cotizacion_taller, acta_policial, …
        description str  — fallback text description when no real image is provided

    Returns a partial state update with:
        extracted_data.c_result   dict  — structured extraction
    """
    data: dict = state.get("extracted_data", {})
    file_url: str = data.get("file_url", "")
    doc_type: str = data.get("doc_type", "fotos_danos")
    description: str = data.get("description", "No document description provided.")

    logger.info("[Agent C] Extracting %s for claim %s", doc_type, state["claim_id"])

    system_prompt = _PROMPTS.get(doc_type, _DEFAULT_PROMPT)

    content = _build_content(file_url, fallback_text=f"Document description:\n{description}")

    try:
        client = _get_client()
        response = await client.messages.create(
            model=VLM_MODEL,
            max_tokens=1024,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": content}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        c_result = json.loads(raw)
    except Exception as exc:
        logger.warning("[Agent C] Extraction failed for %s: %s", state["claim_id"], exc)
        c_result = {"error": str(exc), "doc_type": doc_type, "raw_description": description}

    return {
        "extracted_data": {
            **data,
            "c_result": c_result,
        }
    }
