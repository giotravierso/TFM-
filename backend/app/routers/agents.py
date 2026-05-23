from fastapi import APIRouter
from pathlib import Path
import os

router = APIRouter()

_DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).parent.parent.parent.parent / "data")))
_MODEL_PATH = _DATA_DIR / "models" / "agent_f_xgboost.pkl"
_OFAC_PATH = _DATA_DIR / "ofac_mock.json"
_DATASET_PATH = _DATA_DIR / "synthetic" / "claims_dataset.json"
_POLICIES_DIR = _DATA_DIR / "policies"


def _agent_status(agent_id: str, implemented: bool, notes: str = "") -> dict:
    return {"id": agent_id, "status": "implemented" if implemented else "stub", "notes": notes}


@router.get("/status")
async def agents_status():
    """Return implementation status and artifact availability for all agents."""
    policy_files = list(_POLICIES_DIR.glob("*.md")) if _POLICIES_DIR.exists() else []
    return {
        "agents": [
            _agent_status("agent_a", True, "LangGraph ReAct orchestrator — routes to B–H"),
            _agent_status("agent_b", True, "Document validation + R-SP-PCS-09-001/002"),
            _agent_status("agent_c", True, "Claude Vision VLM — damage photos, quotes, police reports"),
            _agent_status("agent_d", True, "Coverage RAG (ChromaDB) + hardcoded fallback"),
            _agent_status("agent_e", True, "CoT decision + HITL (4 triggers)"),
            _agent_status("agent_f", True, f"XGBoost judicialization — model_ready={_MODEL_PATH.exists()}"),
            _agent_status("agent_g", True, f"OFAC fuzzy match + fraud score — ofac_list_ready={_OFAC_PATH.exists()}"),
            _agent_status("agent_h", True, "RAG conversational assistant — shares ChromaDB with D"),
        ],
        "artifacts": {
            "xgboost_model": _MODEL_PATH.exists(),
            "ofac_list": _OFAC_PATH.exists(),
            "synthetic_dataset": _DATASET_PATH.exists(),
            "policy_docs_count": len(policy_files),
            "policy_docs": [f.name for f in policy_files],
        },
    }
