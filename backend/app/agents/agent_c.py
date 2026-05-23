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
VLM_MODEL = "claude-sonnet-4-20250514"

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

    # Build message content — use image_url block if we have a real URL,
    # otherwise fall back to text description (PoC mode)
    if file_url and file_url.startswith(("http", "data:")):
        content: list[dict] = [
            {
                "type": "image",
                "source": {
                    "type": "url" if file_url.startswith("http") else "base64",
                    "url": file_url if file_url.startswith("http") else None,
                    "media_type": "image/jpeg",
                    "data": file_url.split(",", 1)[1] if file_url.startswith("data:") else None,
                },
            },
            {"type": "text", "text": "Extract the information as instructed."},
        ]
        # Remove None keys
        content[0]["source"] = {k: v for k, v in content[0]["source"].items() if v is not None}
    else:
        content = [{"type": "text", "text": f"Document description:\n{description}"}]

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
