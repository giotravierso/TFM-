"""
Tests for Agent G — Fraud & AML/CFT Compliance.
No external dependencies (uses local ofac_mock.json).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.agents.agent_g import _ofac_match, _load_ofac, check_fraud_and_compliance


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _state(
    client_name: str = "JUAN PEREZ GARCIA",
    conductor_name: str = "JUAN PEREZ GARCIA",
    claim_type: str = "danys_propis",
    amount: float = 100_000,
    prior_claims: int = 0,
    incident_time: str = "14:30",
    docs_complete: bool = True,
) -> dict:
    return {
        "claim_id": "EXP-TEST-G-001",
        "messages": [],
        "status": "open",
        "extracted_data": {
            "client_name": client_name,
            "conductor_name": conductor_name,
            "claim_type": claim_type,
            "amount_requested": amount,
            "prior_claims_count": prior_claims,
            "incident_time": incident_time,
            "b_docs_complete": docs_complete,
        },
        "policy_check": None,
        "decision": None,
        "hitl_required": False,
    }


class TestOFACMatching:
    def test_exact_ofac_name_matches(self):
        ofac = _load_ofac()
        assert len(ofac) == 30, "OFAC mock list should have 30 entries"
        matched, name, score = _ofac_match(ofac[0], ofac)
        assert matched is True
        assert score == 100.0

    def test_clean_name_does_not_match(self):
        ofac = _load_ofac()
        matched, _, _ = _ofac_match("JUAN PEREZ GARCIA", ofac)
        assert matched is False

    def test_near_match_above_threshold(self):
        # Slight variation of an OFAC name should still match
        ofac = _load_ofac()
        first = ofac[0]  # e.g. "FICTICIO ALVAREZ MENDOZA RODRIGO"
        typo = first.replace("RODRIGO", "RODRIG0")  # zero instead of O
        matched, _, score = _ofac_match(typo, ofac)
        assert matched is True  # token_sort_ratio >= 85

    def test_completely_different_name_does_not_match(self):
        ofac = _load_ofac()
        matched, _, score = _ofac_match("SMITH JOHN WILLIAM", ofac)
        assert matched is False

    def test_empty_name_does_not_match(self):
        ofac = _load_ofac()
        matched, _, score = _ofac_match("", ofac)
        assert matched is False


class TestFraudScore:
    def test_clean_claim_has_zero_score(self):
        state = _state(amount=50_000, prior_claims=0, incident_time="14:00", docs_complete=True)
        result = run(check_fraud_and_compliance(state))
        assert result["extracted_data"]["g_fraud_score"] == 0.0

    def test_high_amount_danys_propis_adds_score(self):
        state = _state(claim_type="danys_propis", amount=600_000, docs_complete=True)
        result = run(check_fraud_and_compliance(state))
        assert result["extracted_data"]["g_fraud_score"] >= 0.20

    def test_three_prior_claims_adds_score(self):
        state = _state(prior_claims=3)
        result = run(check_fraud_and_compliance(state))
        assert result["extracted_data"]["g_fraud_score"] >= 0.25

    def test_two_prior_claims_adds_less_than_three(self):
        state2 = _state(prior_claims=2)
        state3 = _state(prior_claims=3)
        score2 = run(check_fraud_and_compliance(state2))["extracted_data"]["g_fraud_score"]
        score3 = run(check_fraud_and_compliance(state3))["extracted_data"]["g_fraud_score"]
        assert score2 < score3

    def test_nocturnal_incident_adds_score(self):
        state = _state(incident_time="02:30")
        result = run(check_fraud_and_compliance(state))
        assert result["extracted_data"]["g_fraud_score"] >= 0.15

    def test_daytime_incident_does_not_add_nocturnal_score(self):
        state = _state(incident_time="10:00")
        result = run(check_fraud_and_compliance(state))
        assert result["extracted_data"]["g_fraud_score"] < 0.15

    def test_incomplete_docs_adds_score(self):
        state = _state(docs_complete=False)
        result = run(check_fraud_and_compliance(state))
        assert result["extracted_data"]["g_fraud_score"] >= 0.10

    def test_score_never_exceeds_one(self):
        state = _state(
            claim_type="danys_propis", amount=600_000,
            prior_claims=4, incident_time="03:00", docs_complete=False,
        )
        result = run(check_fraud_and_compliance(state))
        assert result["extracted_data"]["g_fraud_score"] <= 1.0


class TestDueDiligence:
    def test_clean_claim_is_simplificada(self):
        state = _state()
        result = run(check_fraud_and_compliance(state))
        assert result["extracted_data"]["g_due_diligence"] == "simplificada"

    def test_high_fraud_score_is_ampliada(self):
        # Score breakdown: 3 prior claims (+0.25) + nocturnal (+0.15) + incomplete docs (+0.10)
        # + danys_propis high amount (+0.20) = 0.70 > 0.50 → ampliada
        state = _state(
            claim_type="danys_propis", amount=600_000,
            prior_claims=3, incident_time="02:00", docs_complete=False,
        )
        result = run(check_fraud_and_compliance(state))
        assert result["extracted_data"]["g_fraud_score"] > 0.50
        assert result["extracted_data"]["g_due_diligence"] == "ampliada"

    def test_ofac_match_forces_hitl(self):
        ofac = _load_ofac()
        flagged_name = ofac[5]
        state = _state(conductor_name=flagged_name)
        result = run(check_fraud_and_compliance(state))
        assert result["extracted_data"]["g_ofac_flagged"] is True
        assert result["hitl_required"] is True
        assert result["extracted_data"]["g_due_diligence"] == "ampliada"
