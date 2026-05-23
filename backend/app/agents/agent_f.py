"""
Agent F — Judicialization Risk Prediction (XGBoost).

Predicts probability that a claim will escalate to litigation (SP-PCS-022).
Implements subproceso SP-PCS-022.3 (proactive prevention — not yet in production
at Seguros Pepín as of the TFM baseline).

Features (10):
  1.  amount_requested / 1_000_000      (normalized)
  2.  prior_claims_count
  3.  days_since_incident
  4.  interaction_count
  5.  proposal_rejected_before          (0/1)
  6.  claim_type_RC                     (0/1)
  7.  claim_type_DPA                    (0/1)
  8.  claim_type_danys_propis           (0/1)
  9.  risk_score                        (from Agent G)
  10. channel_phone                     (0/1)

Risk levels:
  HIGH    probability > 0.60
  MEDIUM  probability > 0.30
  LOW     otherwise

Falls back to heuristic scoring when the model artifact is not found.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.orchestrator import ClaimState

logger = logging.getLogger(__name__)

_DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).parent.parent.parent.parent / "data")))
MODEL_PATH = _DATA_DIR / "models" / "agent_f_xgboost.pkl"

_model = None


def _load_model():
    global _model
    if _model is not None:
        return _model
    if not MODEL_PATH.exists():
        logger.info("[Agent F] Model not found at %s — using heuristic fallback", MODEL_PATH)
        return None
    try:
        import pickle
        with MODEL_PATH.open("rb") as fh:
            _model = pickle.load(fh)
        logger.info("[Agent F] XGBoost model loaded from %s", MODEL_PATH)
    except Exception as exc:
        logger.warning("[Agent F] Could not load model: %s", exc)
    return _model


def _build_features(data: dict) -> list[float]:
    claim_type = data.get("claim_type", "danys_propis")
    return [
        float(data.get("amount_requested", 0)) / 1_000_000,
        float(data.get("prior_claims_count", 0)),
        float(data.get("days_since_incident", 0)),
        float(data.get("interaction_count", 1)),
        float(bool(data.get("proposal_rejected_before", False))),
        float(claim_type == "RC"),
        float(claim_type == "DPA"),
        float(claim_type == "danys_propis"),
        float(data.get("g_risk_score", data.get("g_fraud_score", 0))),
        float(data.get("channel", "") == "phone"),
    ]


def _heuristic_score(data: dict) -> float:
    """Rule-based judicialization probability when model is absent."""
    score = 0.04
    claim_type = data.get("claim_type", "")
    amount = float(data.get("amount_requested", 0))
    prior_claims = int(data.get("prior_claims_count", 0))
    interaction_count = int(data.get("interaction_count", 1))
    proposal_rejected = bool(data.get("proposal_rejected_before", False))
    days_since = int(data.get("days_since_incident", 0))

    if claim_type in ("RC", "DPA"):
        score += 0.06
    if amount > 300_000:
        score += 0.05
    if proposal_rejected:
        score += 0.12
    if interaction_count > 5:
        score += 0.05
    if days_since > 30:
        score += 0.03
    if prior_claims >= 2:
        score += 0.04

    return round(min(score, 0.95), 3)


async def predict_judicialization_risk(state: "ClaimState") -> dict:
    """
    Predict judicialization probability and emit risk level + SHAP explanation.

    Reads from state["extracted_data"]:
        claim_type, amount_requested, prior_claims_count, days_since_incident,
        interaction_count, proposal_rejected_before, g_risk_score, channel

    Returns partial state update with:
        extracted_data.f_judi_probability  float
        extracted_data.f_judi_risk_level   str  (HIGH | MEDIUM | LOW)
        extracted_data.f_shap_values       list[float] | None
        extracted_data.f_model_used        str
    """
    data: dict = state.get("extracted_data", {})
    logger.info("[Agent F] Predicting judicialization risk for %s", state["claim_id"])

    model = _load_model()
    shap_values: list[float] | None = None

    if model is not None:
        try:
            import numpy as np
            features = _build_features(data)
            X = np.array([features])
            probability = float(model.predict_proba(X)[0][1])

            # SHAP explanation (best-effort)
            try:
                import shap
                explainer = shap.TreeExplainer(model)
                shap_arr = explainer.shap_values(X)
                shap_values = [round(float(v), 4) for v in shap_arr[0]]
            except Exception:
                pass

            model_used = "xgboost"
        except Exception as exc:
            logger.warning("[Agent F] Inference failed: %s — using heuristic", exc)
            probability = _heuristic_score(data)
            model_used = "heuristic_fallback"
    else:
        probability = _heuristic_score(data)
        model_used = "heuristic_fallback"

    if probability > 0.60:
        risk_level = "HIGH"
    elif probability > 0.30:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    logger.info(
        "[Agent F] %s: probability=%.3f risk=%s model=%s",
        state["claim_id"], probability, risk_level, model_used,
    )

    return {
        "extracted_data": {
            **data,
            "f_judi_probability": round(probability, 4),
            "f_judi_risk_level": risk_level,
            "f_shap_values": shap_values,
            "f_model_used": model_used,
        }
    }
