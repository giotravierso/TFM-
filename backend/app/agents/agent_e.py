"""
Agent E — Decision + HITL (Human-in-the-Loop).

Applies SP-PCS-009 §3.3 HITL thresholds:
  amount > RD$500,000     → HITL (Director de Reclamaciones)
  confidence < 0.75       → HITL (Analista de Reclamaciones)
  fraud_score > 0.30      → HITL (Área de Cumplimiento)
  OFAC flagged            → HITL (Oficial de Cumplimiento)

If no HITL trigger: runs Chain-of-Thought with Claude to decide:
  approve        → status RESOLVED   + calls approve_payment tool
  reject         → status REJECTED   + calls send_rejection tool
  request_info   → status VALIDATING + calls request_more_info tool
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
LLM_MODEL = "claude-sonnet-4-20250514"

HITL_THRESHOLD_AMOUNT = 500_000
HITL_THRESHOLD_CONFIDENCE = 0.75
HITL_THRESHOLD_FRAUD = 0.30

_client: AsyncAnthropic | None = None


def _llm() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _client


_DECISION_SYSTEM = """
Eres el Agente E del sistema Smart-Claims de Seguros Pepín S.A.
Tu rol es tomar la decisión final sobre una reclamación de seguro vehicular.

Debes razonar paso a paso (Chain of Thought) usando los datos proporcionados y
luego emitir tu decisión. Responde ÚNICAMENTE con JSON válido con las claves:

  decision      "approve" | "reject" | "request_info"
  rationale     string explicando el razonamiento (mínimo 3 oraciones)
  confidence    float 0-1 de tu confianza en la decisión

Reglas de negocio obligatorias:
- Si danys_mecanics: siempre reject.
- Si documentos incompletos: request_info (no reject).
- Si monto neto pagable > 0 y cobertura confirmada y docs completos: approve.
- Si cobertura no aplicable o exclusión: reject con justificación clara.
""".strip()


async def decide_claim(state: "ClaimState") -> dict:
    """
    Decide approve / reject / request_info or escalate to HITL.

    Reads:
        policy_check.net_payable       float
        policy_check.confidence        float
        policy_check.covered           bool
        extracted_data.g_fraud_score   float
        extracted_data.g_ofac_flagged  bool
        extracted_data.b_docs_complete bool
        extracted_data.b_missing_docs  list[str]
        extracted_data.claim_type      str

    Returns partial state update with:
        decision      str
        status        str
        hitl_required bool
        extracted_data.e_rationale      str
        extracted_data.e_cot_full       str
    """
    data: dict = state.get("extracted_data", {})
    policy: dict = state.get("policy_check") or {}

    net_payable: float = float(policy.get("net_payable", 0))
    confidence: float = float(policy.get("confidence", 0.80))
    covered: bool = bool(policy.get("covered", True))
    fraud_score: float = float(data.get("g_fraud_score", 0))
    ofac_flagged: bool = bool(data.get("g_ofac_flagged", False))
    docs_complete: bool = bool(data.get("b_docs_complete", True))
    missing_docs: list[str] = data.get("b_missing_docs", [])
    claim_type: str = data.get("claim_type", "danys_propis")

    logger.info(
        "[Agent E] Evaluating %s: net=%.0f conf=%.2f fraud=%.3f",
        state["claim_id"], net_payable, confidence, fraud_score,
    )

    # ── HITL triggers ─────────────────────────────────────────────────────────
    hitl_reason: str = ""
    if ofac_flagged:
        hitl_reason = "Coincidencia en lista OFAC — revisión urgente por Oficial de Cumplimiento"
    elif net_payable > HITL_THRESHOLD_AMOUNT:
        hitl_reason = f"Monto neto RD${net_payable:,.0f} supera RD$500,000 — revisión del Director"
    elif fraud_score > HITL_THRESHOLD_FRAUD:
        hitl_reason = f"Score fraude {fraud_score:.0%} > 30% — revisión por Área de Cumplimiento"
    elif confidence < HITL_THRESHOLD_CONFIDENCE:
        hitl_reason = f"Confianza cobertura {confidence:.0%} < 75% — revisión por Analista"

    if hitl_reason:
        logger.info("[Agent E] HITL for %s: %s", state["claim_id"], hitl_reason)
        return {
            "decision": "hitl",
            "status": "PENDING_REVIEW",
            "hitl_required": True,
            "extracted_data": {
                **data,
                "e_rationale": hitl_reason,
                "e_cot_full": f"HITL escalado: {hitl_reason}",
            },
        }

    # ── Chain-of-Thought decision via Claude ──────────────────────────────────
    user_msg = json.dumps({
        "claim_id": state["claim_id"],
        "claim_type": claim_type,
        "covered": covered,
        "net_payable_RD": net_payable,
        "confidence": confidence,
        "docs_complete": docs_complete,
        "missing_docs": missing_docs,
        "fraud_score": fraud_score,
        "ofac_flagged": ofac_flagged,
        "policy_section": policy.get("policy_section", ""),
    }, ensure_ascii=False, indent=2)

    try:
        resp = await _llm().messages.create(
            model=LLM_MODEL,
            max_tokens=1024,
            temperature=0,
            system=_DECISION_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        llm_out = json.loads(raw)
        decision: str = llm_out.get("decision", "request_info")
        rationale: str = llm_out.get("rationale", "")
        cot_full: str = raw
    except Exception as exc:
        logger.warning("[Agent E] LLM failed (%s) — falling back to rule-based decision", exc)
        decision, rationale, cot_full = _rule_based_decision(
            claim_type, covered, docs_complete, missing_docs, net_payable
        )

    status_map = {
        "approve":      "RESOLVED",
        "reject":       "REJECTED",
        "request_info": "VALIDATING",
    }
    status = status_map.get(decision, "VALIDATING")

    logger.info("[Agent E] %s → %s", state["claim_id"], decision)

    return {
        "decision": decision,
        "status": status,
        "hitl_required": False,
        "extracted_data": {
            **data,
            "e_rationale": rationale,
            "e_cot_full": cot_full,
        },
    }


def _rule_based_decision(
    claim_type: str,
    covered: bool,
    docs_complete: bool,
    missing_docs: list[str],
    net_payable: float,
) -> tuple[str, str, str]:
    """Deterministic fallback when LLM is unavailable."""
    if claim_type == "danys_mecanics":
        return "reject", "Daños mecánicos no cubiertos (§2.5).", "rule:danys_mecanics"
    if not covered:
        return "reject", "Cobertura no aplica para este tipo de reclamación.", "rule:not_covered"
    if not docs_complete:
        return (
            "request_info",
            f"Documentos faltantes: {', '.join(missing_docs)}.",
            "rule:missing_docs",
        )
    if net_payable > 0:
        return "approve", "Cobertura confirmada, documentos completos, monto dentro del límite.", "rule:approve"
    return "reject", "Monto neto pagable es RD$0 — deducible cubre el total.", "rule:deductible_covers_all"
