"""
Agent D — Coverage RAG.

Queries ChromaDB (smart_claims_policies) with claim details, then uses Claude
to interpret the relevant policy sections and determine:

  covered        bool
  max_coverage   float   (RD$)
  deductible     float   (RD$)
  net_payable    float   (RD$)
  policy_section str
  confidence     float   0–1

Applies business rule R-SP-PCS-09-003 (prior claims reduce available coverage)
and R-SP-PCS-09-004 (deductible applies; if assessed < deductible, insurer pays
nothing).

Falls back to hardcoded SP-PCS-009 limits when ChromaDB is unavailable.
"""
from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

from anthropic import AsyncAnthropic

from app.rag.retriever import get_coverage_retriever

if TYPE_CHECKING:
    from app.agents.orchestrator import ClaimState

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODEL = "claude-sonnet-4-20250514"

# Hardcoded fallback — mirrors poliza_sp_pcs_009.md
_FALLBACK: dict[str, dict] = {
    "danys_propis":   {"covered": True,  "max": 500_000,   "deductible": 5_000,  "section": "§2.1"},
    "DPA":            {"covered": True,  "max": 1_000_000, "deductible": 0,       "section": "§2.2"},
    "RC":             {"covered": True,  "max": 2_000_000, "deductible": 0,       "section": "§2.3"},
    "robatori":       {"covered": True,  "max": 800_000,   "deductible": 10_000,  "section": "§2.4"},
    "danys_mecanics": {"covered": False, "max": 0,         "deductible": 0,       "section": "§2.5"},
}

_client: AsyncAnthropic | None = None


def _llm() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _apply_rules(
    claim_type: str,
    amount_requested: float,
    prior_coverage_used: float,
    max_coverage: float,
    deductible: float,
    covered: bool,
) -> dict:
    """Apply R-SP-PCS-09-003 and R-SP-PCS-09-004."""
    if not covered:
        return {"covered": False, "net_payable": 0.0, "deductible": 0.0, "max_coverage": 0.0}

    # R-SP-PCS-09-003: reduce coverage by prior claims consumption
    available = max(0.0, max_coverage - prior_coverage_used)

    # R-SP-PCS-09-004: deductible applies; if assessed < deductible → insurer pays nothing
    payable = max(0.0, min(amount_requested, available) - deductible)
    if amount_requested < deductible:
        payable = 0.0  # asegurado paga el total

    return {
        "covered": True,
        "max_coverage": available,
        "deductible": deductible,
        "net_payable": round(payable, 2),
    }


async def check_policy_coverage(state: "ClaimState") -> dict:
    """
    Determine coverage for the claim using RAG + Claude.

    Reads from state["extracted_data"]:
        claim_type              str
        amount_requested        float
        prior_coverage_used     float   (default 0)
        description             str     (optional, for context)

    Returns a partial state update with key:
        policy_check    dict with covered, max_coverage, deductible, net_payable,
                        policy_section, confidence, context_chunks (list)
    """
    data: dict = state.get("extracted_data", {})
    claim_type: str = data.get("claim_type", "danys_propis")
    amount: float = float(data.get("amount_requested", 0))
    prior_used: float = float(data.get("prior_coverage_used", 0))
    description: str = data.get("description", "")

    logger.info("[Agent D] Checking coverage for %s — type=%s amount=%.0f",
                state["claim_id"], claim_type, amount)

    # ── Try RAG ───────────────────────────────────────────────────────────────
    retriever = await get_coverage_retriever()
    context_chunks: list[dict] = []
    rag_context = ""

    if retriever is not None:
        query = f"Cobertura para {claim_type}. Monto: RD${amount:,.0f}. {description}"
        context_chunks = retriever.query(query, n_results=4)
        rag_context = "\n---\n".join(c["document"] for c in context_chunks)

    # ── Use Claude to interpret policy ────────────────────────────────────────
    if rag_context:
        system = (
            "Eres un experto en pólizas de seguro vehicular de Seguros Pepín (SP-PCS-009). "
            "Basándote SOLO en las secciones de póliza proporcionadas, determina la cobertura "
            "y devuelve ÚNICAMENTE JSON válido con estas claves: "
            "covered (bool), max_coverage (float en RD$), deductible (float en RD$), "
            "policy_section (str), confidence (float 0-1), rationale (str)."
        )
        user_msg = (
            f"Tipo de reclamación: {claim_type}\n"
            f"Monto solicitado: RD${amount:,.2f}\n"
            f"Reclamaciones previas consumidas: RD${prior_used:,.2f}\n\n"
            f"Secciones relevantes de la póliza:\n{rag_context}"
        )
        try:
            resp = await _llm().messages.create(
                model=LLM_MODEL,
                max_tokens=512,
                temperature=0,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = resp.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            llm_result = json.loads(raw)
            covered = bool(llm_result.get("covered", False))
            max_cov = float(llm_result.get("max_coverage", 0))
            deductible = float(llm_result.get("deductible", 0))
            section = llm_result.get("policy_section", "")
            confidence = float(llm_result.get("confidence", 0.80))
        except Exception as exc:
            logger.warning("[Agent D] LLM parse failed (%s) — using fallback", exc)
            rag_context = ""  # trigger fallback below

    # ── Fallback to hardcoded rules ───────────────────────────────────────────
    if not rag_context:
        fb = _FALLBACK.get(claim_type, _FALLBACK["danys_propis"])
        covered = fb["covered"]
        max_cov = fb["max"]
        deductible = fb["deductible"]
        section = fb["section"]
        confidence = 0.85  # hardcoded rules are reliable

    # ── Apply business rules R-SP-PCS-09-003/004 ─────────────────────────────
    financials = _apply_rules(claim_type, amount, prior_used, max_cov, deductible, covered)

    policy_check = {
        **financials,
        "policy_section": section,
        "confidence": confidence,
        "context_chunks": context_chunks,
    }

    logger.info(
        "[Agent D] %s: covered=%s net_payable=%.0f confidence=%.2f",
        state["claim_id"], financials["covered"], financials["net_payable"], confidence,
    )
    return {"policy_check": policy_check}
