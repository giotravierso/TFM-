"""
Agent G — Fraud & AML/CFT Compliance.

Step 1: Fuzzy OFAC/UN matching (rapidfuzz token_sort_ratio ≥ 85)
        Checks both client_name and conductor_name against data/ofac_mock.json.
        Any match → is_flagged=True → forces HITL (Oficial de Cumplimiento).

Step 2: Heuristic fraud score (0.0–1.0) based on PEPIN-POL-CP-0006:
        +0.20  danys_propis AND amount > RD$500,000
        +0.25  prior_claims ≥ 3
        +0.10  prior_claims == 2
        +0.15  incident between 00:00–04:59
        +0.10  incomplete documents

Due-diligence level:
        ampliada    if flagged OR score > 0.50
        simplificada  otherwise
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

if TYPE_CHECKING:
    from app.agents.orchestrator import ClaimState

logger = logging.getLogger(__name__)

_DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).parent.parent.parent.parent / "data")))
OFAC_PATH = _DATA_DIR / "ofac_mock.json"
OFAC_THRESHOLD = 85  # rapidfuzz token_sort_ratio

_ofac_list: list[str] | None = None


def _load_ofac() -> list[str]:
    global _ofac_list
    if _ofac_list is None:
        try:
            _ofac_list = json.loads(OFAC_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Cannot load OFAC list: %s", exc)
            _ofac_list = []
    return _ofac_list


def _ofac_match(name: str, ofac_list: list[str]) -> tuple[bool, str, float]:
    """Return (matched, matched_name, score)."""
    if not name:
        return False, "", 0.0
    name_upper = name.upper().strip()
    best_score = 0.0
    best_match = ""
    for entry in ofac_list:
        score = fuzz.token_sort_ratio(name_upper, entry.upper())
        if score > best_score:
            best_score = score
            best_match = entry
    if best_score >= OFAC_THRESHOLD:
        return True, best_match, best_score
    return False, "", best_score


async def check_fraud_and_compliance(state: "ClaimState") -> dict:
    """
    Run OFAC fuzzy matching and compute heuristic fraud score.

    Reads from state["extracted_data"]:
        client_name         str
        conductor_name      str
        claim_type          str
        amount_requested    float
        prior_claims_count  int
        incident_time       str   (HH:MM, optional)
        b_docs_complete     bool  (from Agent B, optional)

    Returns partial state update with key extracted_data containing:
        g_ofac_flagged          bool
        g_ofac_match_name       str
        g_ofac_match_score      float
        g_fraud_score           float
        g_risk_score            float   (alias used by Agent F)
        g_due_diligence         str     (simplificada | ampliada)
        hitl_required           bool    (True if flagged)
    """
    data: dict = state.get("extracted_data", {})
    client_name: str = data.get("client_name", "")
    conductor_name: str = data.get("conductor_name", "")
    claim_type: str = data.get("claim_type", "danys_propis")
    amount: float = float(data.get("amount_requested", 0))
    prior_claims: int = int(data.get("prior_claims_count", 0))
    incident_time: str = data.get("incident_time", "12:00")
    docs_complete: bool = bool(data.get("b_docs_complete", True))

    logger.info("[Agent G] Compliance check for %s", state["claim_id"])

    ofac_list = _load_ofac()

    # ── Step 1: OFAC fuzzy match ──────────────────────────────────────────────
    client_flagged, client_match, client_score = _ofac_match(client_name, ofac_list)
    cond_flagged, cond_match, cond_score = _ofac_match(conductor_name, ofac_list)

    is_flagged = client_flagged or cond_flagged
    match_name = client_match if client_flagged else cond_match
    match_score = max(client_score, cond_score)

    if is_flagged:
        logger.warning(
            "[Agent G] OFAC match for claim %s: '%s' (score=%.1f)",
            state["claim_id"], match_name, match_score,
        )

    # ── Step 2: Heuristic fraud score ─────────────────────────────────────────
    fraud_score = 0.0
    if claim_type == "danys_propis" and amount > 500_000:
        fraud_score += 0.20
    if prior_claims >= 3:
        fraud_score += 0.25
    elif prior_claims == 2:
        fraud_score += 0.10
    try:
        hour = int(incident_time.split(":")[0])
        if 0 <= hour < 5:
            fraud_score += 0.15
    except ValueError:
        pass
    if not docs_complete:
        fraud_score += 0.10
    fraud_score = round(min(fraud_score, 1.0), 3)

    due_diligence = "ampliada" if (is_flagged or fraud_score > 0.50) else "simplificada"

    hitl_required = state.get("hitl_required", False) or is_flagged

    logger.info(
        "[Agent G] %s: flagged=%s fraud_score=%.3f due_diligence=%s",
        state["claim_id"], is_flagged, fraud_score, due_diligence,
    )

    return {
        "hitl_required": hitl_required,
        "extracted_data": {
            **data,
            "g_ofac_flagged": is_flagged,
            "g_ofac_match_name": match_name,
            "g_ofac_match_score": round(match_score, 1),
            "g_fraud_score": fraud_score,
            "g_risk_score": fraud_score,  # alias consumed by Agent F
            "g_due_diligence": due_diligence,
        },
    }
