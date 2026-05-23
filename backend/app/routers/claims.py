from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.agents.orchestrator import ask_expert, process_claim

router = APIRouter()


class ClaimRequest(BaseModel):
    claim_id: str
    client_id: str
    claim_type: str
    channel: str = "email"
    text: str
    amount_requested: float | None = None
    # Optional fields consumed by Agent B / G
    conductor_name: str | None = None
    client_name: str | None = None
    submitted_docs: list[str] = []
    prior_claims_count: int = 0
    days_since_incident: int = 0
    interaction_count: int = 1
    proposal_rejected_before: bool = False
    incident_time: str = "12:00"


class ClaimResponse(BaseModel):
    claim_id: str
    status: str
    decision: str | None
    hitl_required: bool
    net_payable: float | None
    rationale: str | None
    judi_risk_level: str | None
    message: str


class ExpertQueryRequest(BaseModel):
    claim_id: str
    query: str


class ExpertQueryResponse(BaseModel):
    claim_id: str
    answer: str
    sources: list[str]


@router.post("/", response_model=ClaimResponse)
async def create_claim(claim: ClaimRequest):
    """Submit a claim for processing by the Smart-Claims agent graph."""
    # Build initial extracted_data from the request payload
    extracted_data = {
        "claim_type": claim.claim_type,
        "amount_requested": claim.amount_requested or 0.0,
        "client_name": claim.client_name or claim.client_id,
        "conductor_name": claim.conductor_name or claim.client_name or claim.client_id,
        "submitted_docs": claim.submitted_docs,
        "prior_claims_count": claim.prior_claims_count,
        "days_since_incident": claim.days_since_incident,
        "interaction_count": claim.interaction_count,
        "proposal_rejected_before": claim.proposal_rejected_before,
        "incident_time": claim.incident_time,
        "channel": claim.channel,
        "description": claim.text,
    }

    # Embed extracted_data context into claim_text for the triage LLM
    import json
    enriched_text = (
        f"{claim.text}\n\n[CONTEXT] {json.dumps(extracted_data, ensure_ascii=False)}"
    )

    try:
        final_state = await process_claim(claim.claim_id, enriched_text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent processing failed: {exc}") from exc

    policy = final_state.get("policy_check") or {}
    data = final_state.get("extracted_data", {})

    return ClaimResponse(
        claim_id=claim.claim_id,
        status=str(final_state.get("status", "open")),
        decision=final_state.get("decision"),
        hitl_required=bool(final_state.get("hitl_required", False)),
        net_payable=policy.get("net_payable"),
        rationale=data.get("e_rationale"),
        judi_risk_level=data.get("f_judi_risk_level"),
        message="Reclamación procesada por el sistema Smart-Claims Agent.",
    )


@router.get("/{claim_id}")
async def get_claim(claim_id: str):
    """Get claim status (stub — full DB integration in Entrega 3)."""
    return {"claim_id": claim_id, "status": "open"}


@router.post("/expert-query", response_model=ExpertQueryResponse)
async def expert_query(req: ExpertQueryRequest):
    """Invoke Agent H to answer a natural-language question about policy or claim."""
    try:
        result = await ask_expert(req.claim_id, req.query)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent H failed: {exc}") from exc

    data = result.get("extracted_data", {})
    return ExpertQueryResponse(
        claim_id=req.claim_id,
        answer=data.get("h_result", ""),
        sources=data.get("h_sources", []),
    )
