"""
Agent B — Document Validation.

Verifies that the submitted documents match the requirements for the claim
type (SP-PCS-009 §2, R-SP-PCS-09-001).  Applies two additional business rules:

  R-SP-PCS-09-002  If conductor ≠ policy owner, flag the cheque so it is
                   issued to the policy owner (not the conductor).
  Immediate reject If claim_type == 'danys_mecanics' (not covered §2.5).

After its own validation, Agent B triggers Agent G for early OFAC screening.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.orchestrator import ClaimState

logger = logging.getLogger(__name__)

# ── Required documents per claim type (SP-PCS-009 §2) ─────────────────────────

REQUIRED_DOCS: dict[str, list[str]] = {
    "danys_propis": [
        "formulario_aviso_accidente", "acta_policial",
        "licencia_conducir", "cedula", "fotos_danos", "cotizacion_taller",
    ],
    "DPA": [
        "aviso_siniestro", "acta_policial_certificada", "acta_conciliacion",
        "presupuesto_piezas", "fotos_danos_con_placa", "matricula",
        "cedula", "licencia_conducir",
    ],
    "RC": [
        "aviso_siniestro", "acta_policial",
        "cedula", "licencia_conducir", "fotos_danos",
    ],
    "robatori": [
        "denuncia_policial", "licencia_conducir", "cedula", "matricula",
    ],
    "danys_mecanics": [],  # not covered — immediate reject
}


async def validate_claim_documents(state: "ClaimState") -> dict:
    """
    Validate documents and apply business rules B.

    Reads from state["extracted_data"]:
        claim_type          str
        submitted_docs      list[str]  — document types present in the claim
        conductor_name      str
        client_name         str        — policy owner

    Returns a partial state update with keys:
        extracted_data.b_missing_docs   list[str]
        extracted_data.b_docs_complete  bool
        extracted_data.flag_cheque_propietario  bool
        decision                        "reject" | None
        status                          ClaimStatus value (string)
    """
    data: dict = state.get("extracted_data", {})
    claim_type: str = data.get("claim_type", "danys_propis")
    submitted: list[str] = data.get("submitted_docs", [])
    conductor: str = data.get("conductor_name", "")
    client: str = data.get("client_name", "")

    logger.info("[Agent B] Validating %s — type=%s", state["claim_id"], claim_type)

    # ── Immediate reject: mechanical damage is not covered ────────────────────
    if claim_type == "danys_mecanics":
        logger.info("[Agent B] Auto-reject: danys_mecanics not covered (§2.5)")
        return {
            "decision": "reject",
            "status": "REJECTED",
            "extracted_data": {
                **data,
                "b_missing_docs": [],
                "b_docs_complete": False,
                "b_reject_reason": "Daños mecánicos no cubiertos según SP-PCS-009 §2.5",
                "flag_cheque_propietario": False,
            },
        }

    # ── R-SP-PCS-09-001: Check required documents ─────────────────────────────
    required = REQUIRED_DOCS.get(claim_type, [])
    missing = [doc for doc in required if doc not in submitted]
    docs_complete = len(missing) == 0

    if missing:
        logger.info("[Agent B] Missing docs for %s: %s", state["claim_id"], missing)

    # ── R-SP-PCS-09-002: Conductor vs owner ───────────────────────────────────
    flag_cheque = bool(conductor and client and conductor.strip() != client.strip())
    if flag_cheque:
        logger.info(
            "[Agent B] Conductor (%s) ≠ owner (%s) — cheque will be issued to owner",
            conductor, client,
        )

    return {
        "extracted_data": {
            **data,
            "b_missing_docs": missing,
            "b_docs_complete": docs_complete,
            "flag_cheque_propietario": flag_cheque,
        },
    }
