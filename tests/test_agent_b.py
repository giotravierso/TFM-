"""
Tests for Agent B — Document Validation.
No external dependencies (no DB, no LLM, no ChromaDB).
"""
import asyncio
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.agents.agent_b import validate_claim_documents, REQUIRED_DOCS


def _state(claim_type: str, submitted_docs: list[str], conductor: str = "", client: str = "JUAN PEREZ") -> dict:
    return {
        "claim_id": "EXP-TEST-0001",
        "messages": [],
        "status": "open",
        "extracted_data": {
            "claim_type": claim_type,
            "submitted_docs": submitted_docs,
            "conductor_name": conductor or client,
            "client_name": client,
        },
        "policy_check": None,
        "decision": None,
        "hitl_required": False,
    }


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestRequiredDocs:
    def test_all_claim_types_have_keys(self):
        expected = {"danys_propis", "DPA", "RC", "robatori", "danys_mecanics"}
        assert set(REQUIRED_DOCS.keys()) == expected

    def test_danys_propis_requires_six_docs(self):
        assert len(REQUIRED_DOCS["danys_propis"]) == 6

    def test_danys_mecanics_requires_no_docs(self):
        assert REQUIRED_DOCS["danys_mecanics"] == []

    def test_dpa_requires_eight_docs(self):
        assert len(REQUIRED_DOCS["DPA"]) == 8


class TestMechanicalAutoReject:
    def test_mechanical_is_rejected(self):
        state = _state("danys_mecanics", [])
        result = run(validate_claim_documents(state))
        assert result["decision"] == "reject"
        assert result["status"] == "REJECTED"

    def test_mechanical_reject_reason_is_set(self):
        state = _state("danys_mecanics", [])
        result = run(validate_claim_documents(state))
        assert "2.5" in result["extracted_data"]["b_reject_reason"]


class TestDocumentValidation:
    def test_complete_docs_marks_complete(self):
        docs = REQUIRED_DOCS["danys_propis"].copy()
        state = _state("danys_propis", docs)
        result = run(validate_claim_documents(state))
        assert result["extracted_data"]["b_docs_complete"] is True
        assert result["extracted_data"]["b_missing_docs"] == []

    def test_missing_one_doc(self):
        docs = REQUIRED_DOCS["danys_propis"][:-1]  # drop last
        state = _state("danys_propis", docs)
        result = run(validate_claim_documents(state))
        assert result["extracted_data"]["b_docs_complete"] is False
        assert len(result["extracted_data"]["b_missing_docs"]) == 1

    def test_missing_docs_lists_correct_names(self):
        required = REQUIRED_DOCS["RC"]
        missing_doc = required[-1]
        submitted = required[:-1]
        state = _state("RC", submitted)
        result = run(validate_claim_documents(state))
        assert missing_doc in result["extracted_data"]["b_missing_docs"]

    def test_empty_submission_lists_all_as_missing(self):
        state = _state("robatori", [])
        result = run(validate_claim_documents(state))
        missing = result["extracted_data"]["b_missing_docs"]
        assert set(missing) == set(REQUIRED_DOCS["robatori"])


class TestChequeOwnerFlag:
    def test_same_conductor_and_owner_no_flag(self):
        state = _state("danys_propis", REQUIRED_DOCS["danys_propis"], client="JUAN PEREZ", conductor="JUAN PEREZ")
        result = run(validate_claim_documents(state))
        assert result["extracted_data"]["flag_cheque_propietario"] is False

    def test_different_conductor_sets_flag(self):
        state = _state("danys_propis", REQUIRED_DOCS["danys_propis"], client="JUAN PEREZ", conductor="MARIA GARCIA")
        result = run(validate_claim_documents(state))
        assert result["extracted_data"]["flag_cheque_propietario"] is True

    def test_no_decision_set_when_docs_incomplete_but_not_mechanical(self):
        state = _state("danys_propis", [])
        result = run(validate_claim_documents(state))
        # Agent B does NOT set decision itself for doc issues (Agent E does)
        assert "decision" not in result or result.get("decision") is None
