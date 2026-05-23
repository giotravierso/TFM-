"""
Tests for the synthetic dataset generator.
Validates distribution requirements and schema correctness.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "data" / "synthetic"))

from generator import generate_claims, REQUIRED_DOCS, COVERAGE, CLAIM_TYPES

CLAIMS = generate_claims()


class TestDistribution:
    def test_generates_100_claims(self):
        assert len(CLAIMS) == 100

    def test_claim_type_counts(self):
        counts = {}
        for c in CLAIMS:
            ct = c["claim_type"]
            counts[ct] = counts.get(ct, 0) + 1
        for ctype, expected_count in CLAIM_TYPES:
            assert counts.get(ctype, 0) == expected_count, f"{ctype}: expected {expected_count}, got {counts.get(ctype, 0)}"

    def test_approve_rate_at_least_30_percent(self):
        approvals = sum(1 for c in CLAIMS if c["ground_truth"]["decision"] == "approve")
        assert approvals / len(CLAIMS) >= 0.30

    def test_reject_includes_all_mechanical(self):
        mechanical = [c for c in CLAIMS if c["claim_type"] == "danys_mecanics"]
        for c in mechanical:
            assert c["ground_truth"]["decision"] == "reject"

    def test_hitl_rate_above_20_percent(self):
        hitl_n = sum(1 for c in CLAIMS if c["ground_truth"]["hitl_required"])
        assert hitl_n / len(CLAIMS) >= 0.20

    def test_judicializado_rate_between_5_and_25_percent(self):
        judi_n = sum(1 for c in CLAIMS if c["ground_truth"]["judicializado"])
        rate = judi_n / len(CLAIMS)
        assert 0.05 <= rate <= 0.25

    def test_ofac_flagged_rate_under_15_percent(self):
        ofac_n = sum(1 for c in CLAIMS if c["compliance"]["ofac_flagged"])
        assert ofac_n / len(CLAIMS) <= 0.15


class TestSchema:
    def test_all_claims_have_required_top_level_keys(self):
        required_keys = {
            "claim_id", "claim_type", "policy_number", "client_name",
            "conductor_name", "conductor_is_owner", "vehicle", "incident",
            "financials", "documents", "history", "channel", "compliance",
            "ground_truth",
        }
        for c in CLAIMS:
            assert required_keys.issubset(set(c.keys())), f"Missing keys in {c['claim_id']}"

    def test_claim_ids_are_unique(self):
        ids = [c["claim_id"] for c in CLAIMS]
        assert len(ids) == len(set(ids))

    def test_financials_schema(self):
        for c in CLAIMS:
            f = c["financials"]
            assert "amount_requested" in f
            assert "net_payable" in f
            assert "max_coverage" in f
            assert "deductible" in f
            assert f["net_payable"] >= 0
            assert f["amount_requested"] >= 0

    def test_net_payable_never_exceeds_max_coverage(self):
        for c in CLAIMS:
            f = c["financials"]
            assert f["net_payable"] <= f["max_coverage"], (
                f"{c['claim_id']}: net_payable {f['net_payable']} > max {f['max_coverage']}"
            )

    def test_danys_mecanics_net_payable_is_zero(self):
        for c in CLAIMS:
            if c["claim_type"] == "danys_mecanics":
                assert c["financials"]["net_payable"] == 0.0

    def test_ground_truth_valid_decisions(self):
        valid = {"approve", "reject", "request_info", "hitl"}
        for c in CLAIMS:
            assert c["ground_truth"]["decision"] in valid

    def test_compliance_fraud_score_in_range(self):
        for c in CLAIMS:
            score = c["compliance"]["fraud_score"]
            assert 0.0 <= score <= 1.0, f"{c['claim_id']}: fraud_score={score}"

    def test_due_diligence_valid_values(self):
        valid = {"simplificada", "ampliada"}
        for c in CLAIMS:
            assert c["compliance"]["due_diligence"] in valid

    def test_history_schema(self):
        for c in CLAIMS:
            h = c["history"]
            assert "prior_claims_count" in h
            assert "interaction_count" in h
            assert "proposal_rejected_before" in h
            assert "days_since_incident" in h
            assert h["prior_claims_count"] >= 0
            assert h["interaction_count"] >= 1


class TestBusinessRules:
    def test_hitl_if_high_net_payable(self):
        for c in CLAIMS:
            net = c["financials"]["net_payable"]
            if net > 500_000:
                assert c["ground_truth"]["hitl_required"], (
                    f"{c['claim_id']}: net_payable={net} should trigger HITL"
                )

    def test_hitl_if_ofac_flagged(self):
        for c in CLAIMS:
            if c["compliance"]["ofac_flagged"]:
                assert c["ground_truth"]["hitl_required"], (
                    f"{c['claim_id']}: OFAC flagged but hitl_required=False"
                )

    def test_mechanical_always_reject(self):
        for c in CLAIMS:
            if c["claim_type"] == "danys_mecanics":
                assert c["ground_truth"]["decision"] == "reject"
                assert not c["ground_truth"]["hitl_required"]

    def test_documents_json_is_serialisable(self):
        # Verify the full dataset can round-trip through JSON
        raw = json.dumps(CLAIMS, ensure_ascii=False)
        reloaded = json.loads(raw)
        assert len(reloaded) == 100
