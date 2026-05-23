"""
Tests for Agent E — Decision + HITL.

Tests the rule-based fallback (_rule_based_decision) and the full
decide_claim flow with mocked state — no LLM calls needed.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.agents.agent_e import (
    _rule_based_decision,
    decide_claim,
    HITL_THRESHOLD_AMOUNT,
    HITL_THRESHOLD_CONFIDENCE,
    HITL_THRESHOLD_FRAUD,
)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _state(
    net_payable: float = 50_000,
    confidence: float = 0.90,
    fraud_score: float = 0.05,
    ofac_flagged: bool = False,
    docs_complete: bool = True,
    missing_docs: list = None,
    claim_type: str = "danys_propis",
    covered: bool = True,
    hitl_required: bool = False,
) -> dict:
    return {
        "claim_id": "EXP-TEST-E-001",
        "messages": [],
        "status": "open",
        "hitl_required": hitl_required,
        "decision": None,
        "extracted_data": {
            "claim_type": claim_type,
            "g_fraud_score": fraud_score,
            "g_ofac_flagged": ofac_flagged,
            "b_docs_complete": docs_complete,
            "b_missing_docs": missing_docs or [],
        },
        "policy_check": {
            "net_payable": net_payable,
            "confidence": confidence,
            "covered": covered,
            "policy_section": "§2.1",
        },
    }


# ── Rule-based fallback tests (deterministic, no LLM) ────────────────────────

class TestRuleBasedDecision:
    def test_mechanical_always_rejects(self):
        decision, rationale, _ = _rule_based_decision("danys_mecanics", True, True, [], 10_000)
        assert decision == "reject"
        assert "2.5" in rationale

    def test_not_covered_rejects(self):
        decision, _, _ = _rule_based_decision("danys_propis", False, True, [], 0)
        assert decision == "reject"

    def test_missing_docs_requests_info(self):
        decision, rationale, _ = _rule_based_decision(
            "danys_propis", True, False, ["acta_policial", "fotos_danos"], 50_000
        )
        assert decision == "request_info"
        assert "acta_policial" in rationale

    def test_valid_claim_approves(self):
        decision, _, _ = _rule_based_decision("danys_propis", True, True, [], 80_000)
        assert decision == "approve"

    def test_zero_net_payable_rejects(self):
        # deductible covers all — net payable 0
        decision, _, _ = _rule_based_decision("danys_propis", True, True, [], 0)
        assert decision == "reject"

    def test_rc_covered_with_docs_approves(self):
        decision, _, _ = _rule_based_decision("RC", True, True, [], 250_000)
        assert decision == "approve"


# ── HITL trigger tests (patching LLM to avoid API calls) ─────────────────────

class TestHITLTriggers:
    def test_ofac_flag_forces_hitl(self):
        state = _state(ofac_flagged=True, net_payable=10_000, confidence=0.95, fraud_score=0.0)
        result = run(decide_claim(state))
        assert result["hitl_required"] is True
        assert result["decision"] == "hitl"
        assert result["status"] == "PENDING_REVIEW"

    def test_high_amount_forces_hitl(self):
        state = _state(net_payable=HITL_THRESHOLD_AMOUNT + 1, confidence=0.95, fraud_score=0.0)
        result = run(decide_claim(state))
        assert result["hitl_required"] is True
        assert result["decision"] == "hitl"

    def test_high_fraud_score_forces_hitl(self):
        state = _state(net_payable=50_000, confidence=0.90, fraud_score=HITL_THRESHOLD_FRAUD + 0.01)
        result = run(decide_claim(state))
        assert result["hitl_required"] is True
        assert result["decision"] == "hitl"

    def test_low_confidence_forces_hitl(self):
        state = _state(net_payable=50_000, confidence=HITL_THRESHOLD_CONFIDENCE - 0.01, fraud_score=0.0)
        result = run(decide_claim(state))
        assert result["hitl_required"] is True
        assert result["decision"] == "hitl"

    def test_clean_claim_does_not_force_hitl(self):
        state = _state(
            net_payable=80_000,
            confidence=0.90,
            fraud_score=0.05,
            ofac_flagged=False,
            docs_complete=True,
        )
        # Patch LLM to return deterministic result
        with patch("app.agents.agent_e._llm") as mock_llm_fn:
            mock_client = AsyncMock()
            mock_response = AsyncMock()
            mock_response.content = [AsyncMock(text='{"decision":"approve","rationale":"Cobertura confirmada.","confidence":0.95}')]
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_llm_fn.return_value = mock_client
            result = run(decide_claim(state))
        assert result["hitl_required"] is False

    def test_hitl_reason_mentions_ofac(self):
        state = _state(ofac_flagged=True)
        result = run(decide_claim(state))
        assert "OFAC" in result["extracted_data"]["e_rationale"]

    def test_hitl_reason_mentions_amount_when_high(self):
        state = _state(net_payable=750_000, confidence=0.95, fraud_score=0.0)
        result = run(decide_claim(state))
        assert "500" in result["extracted_data"]["e_rationale"] or "Director" in result["extracted_data"]["e_rationale"]


# ── LLM fallback on exception ─────────────────────────────────────────────────

class TestLLMFallback:
    def test_falls_back_to_rules_when_llm_fails(self):
        state = _state(
            net_payable=80_000, confidence=0.90, fraud_score=0.05,
            docs_complete=True, covered=True,
        )
        with patch("app.agents.agent_e._llm") as mock_llm_fn:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(side_effect=RuntimeError("API unavailable"))
            mock_llm_fn.return_value = mock_client
            result = run(decide_claim(state))
        # Should fall back to approve via _rule_based_decision
        assert result["decision"] == "approve"
        assert result["hitl_required"] is False

    def test_falls_back_when_llm_returns_invalid_json(self):
        state = _state(
            net_payable=80_000, confidence=0.90, fraud_score=0.05,
            docs_complete=True, covered=True,
        )
        with patch("app.agents.agent_e._llm") as mock_llm_fn:
            mock_client = AsyncMock()
            mock_response = AsyncMock()
            mock_response.content = [AsyncMock(text="not valid json at all")]
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_llm_fn.return_value = mock_client
            result = run(decide_claim(state))
        assert result["decision"] in ("approve", "reject", "request_info", "hitl")


# ── Status mapping tests ──────────────────────────────────────────────────────

class TestStatusMapping:
    def _run_with_decision(self, decision_str: str) -> dict:
        state = _state(net_payable=80_000, confidence=0.90, fraud_score=0.05, docs_complete=True)
        with patch("app.agents.agent_e._llm") as mock_llm_fn:
            mock_client = AsyncMock()
            mock_response = AsyncMock()
            mock_response.content = [AsyncMock(text=f'{{"decision":"{decision_str}","rationale":"test","confidence":0.9}}')]
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_llm_fn.return_value = mock_client
            return run(decide_claim(state))

    def test_approve_maps_to_resolved(self):
        result = self._run_with_decision("approve")
        assert result["status"] == "RESOLVED"

    def test_reject_maps_to_rejected(self):
        result = self._run_with_decision("reject")
        assert result["status"] == "REJECTED"

    def test_request_info_maps_to_validating(self):
        result = self._run_with_decision("request_info")
        assert result["status"] == "VALIDATING"
