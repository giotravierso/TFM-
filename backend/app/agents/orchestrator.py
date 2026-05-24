"""
Agent A — Orchestrator (LangGraph ReAct).

Dispatches to specialist agents B–H in the sequence:
  triage → B (doc validation) → G_early (OFAC) → C (VLM extraction)
         → D (coverage RAG) → G_fraud (fraud score) → F (judicialization)
         → E (decision + HITL)

Agent H is invoked on-demand via the answer_expert_query route whenever the
orchestrator receives an h_query in extracted_data.
"""
from __future__ import annotations

import logging
from typing import Annotated, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from app.tools.claim_tools import AGENT_TOOLS
from app.db.models import ClaimStatus

# ── Specialist agents ──────────────────────────────────────────────────────────
from app.agents.agent_b import validate_claim_documents
from app.agents.agent_c import extract_from_document
from app.agents.agent_d import check_policy_coverage
from app.agents.agent_e import decide_claim
from app.agents.agent_f import predict_judicialization_risk
from app.agents.agent_g import check_fraud_and_compliance
from app.agents.agent_h import answer_expert_query

logger = logging.getLogger(__name__)


# ── State ──────────────────────────────────────────────────────────────────────

class ClaimState(TypedDict):
    claim_id: str
    messages: Annotated[list[BaseMessage], add_messages]
    status: ClaimStatus
    extracted_data: dict
    policy_check: dict | None
    decision: str | None
    hitl_required: bool


# ── LLM (used only in triage node) ────────────────────────────────────────────

def _build_llm() -> ChatAnthropic:
    return ChatAnthropic(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        temperature=0,
    ).bind_tools(AGENT_TOOLS)


# ── Nodes ──────────────────────────────────────────────────────────────────────

def triage_node(state: ClaimState) -> dict:
    """Analyse incoming claim and decide which agent to activate first."""
    llm = _build_llm()
    system = (
        "Ets l'Agent A — Orquestrador del sistema Smart-Claims de Seguros Pepín. "
        "El teu rol és analitzar cada reclamació entrant i decidir quin agent "
        "especialitzat ha d'intervenir primer. Raona pas a pas (Chain of Thought) "
        "abans d'actuar. Sempre justifica la decisió d'enrutament."
    )
    response = llm.invoke([
        {"role": "system", "content": system},
        *state["messages"],
    ])
    return {"messages": [response]}


def route_after_triage(state: ClaimState) -> str:
    """Router: decide next node from tool_calls in last message."""
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        tool_name = last.tool_calls[0]["name"]
        routing_map = {
            "validate_documents": "agent_b",
            "extract_multimodal":  "agent_c",
            "check_policy":        "agent_d",
            "resolve_claim":       "agent_e",
            "check_fraud":         "agent_g",
        }
        return routing_map.get(tool_name, END)
    # No tool call — check if there is an h_query waiting
    if state.get("extracted_data", {}).get("h_query"):
        return "agent_h"
    return END


async def agent_b_node(state: ClaimState) -> dict:
    update = await validate_claim_documents(state)
    # Immediately route to Agent G for early OFAC check after doc validation
    return update


async def agent_c_node(state: ClaimState) -> dict:
    return await extract_from_document(state)


async def agent_d_node(state: ClaimState) -> dict:
    return await check_policy_coverage(state)


async def agent_e_node(state: ClaimState) -> dict:
    return await decide_claim(state)


async def agent_f_node(state: ClaimState) -> dict:
    return await predict_judicialization_risk(state)


async def agent_g_node(state: ClaimState) -> dict:
    return await check_fraud_and_compliance(state)


async def agent_h_node(state: ClaimState) -> dict:
    return await answer_expert_query(state)


def hitl_node(state: ClaimState) -> dict:
    """Pause flow for human review."""
    logger.info("HITL activat per l'expedient %s", state["claim_id"])
    return {
        "hitl_required": True,
        "status": ClaimStatus.PENDING_REVIEW,
    }


def route_after_g(state: ClaimState) -> str:
    """After fraud check, go to F (judicialization) or HITL if flagged."""
    if state.get("hitl_required"):
        return "hitl"
    return "agent_f"


def route_after_f(state: ClaimState) -> str:
    """After judicialization prediction, always proceed to E for final decision."""
    return "agent_e"


def route_after_e(state: ClaimState) -> str:
    """After decision, go to HITL or END."""
    if state.get("hitl_required"):
        return "hitl"
    return END


# ── Graph ──────────────────────────────────────────────────────────────────────

def build_orchestrator() -> StateGraph:
    graph = StateGraph(ClaimState)

    graph.add_node("triage",   triage_node)
    graph.add_node("hitl",     hitl_node)
    graph.add_node("agent_b",  agent_b_node)
    graph.add_node("agent_c",  agent_c_node)
    graph.add_node("agent_d",  agent_d_node)
    graph.add_node("agent_e",  agent_e_node)
    graph.add_node("agent_f",  agent_f_node)
    graph.add_node("agent_g",  agent_g_node)
    graph.add_node("agent_h",  agent_h_node)

    graph.set_entry_point("triage")
    graph.add_conditional_edges("triage", route_after_triage)

    # Main pipeline: B → G → (HITL | F) → E → (HITL | END)
    graph.add_edge("agent_b", "agent_g")
    graph.add_conditional_edges("agent_g", route_after_g)
    graph.add_edge("agent_f", "agent_c")   # C runs after F (VLM enrichment)
    graph.add_edge("agent_c", "agent_d")   # D needs C's extraction
    graph.add_edge("agent_d", "agent_e")   # E decides using D's coverage result
    graph.add_conditional_edges("agent_e", route_after_e)

    # H is a leaf — answers a query and ends
    graph.add_edge("agent_h", END)

    return graph.compile()


# ── Public API ─────────────────────────────────────────────────────────────────

orchestrator = build_orchestrator()


async def process_claim(claim_id: str, claim_text: str) -> ClaimState:
    """
    Public entry point: receive a claim and execute the agent graph.

    Args:
        claim_id:   Unique claim identifier.
        claim_text: Claim description (email body, web form, etc.).

    Returns:
        Final graph state with decision and CoT reasoning.
    """
    initial_state: ClaimState = {
        "claim_id": claim_id,
        "messages": [HumanMessage(content=claim_text)],
        "status": ClaimStatus.OPEN,
        "extracted_data": {},
        "policy_check": None,
        "decision": None,
        "hitl_required": False,
    }
    return await orchestrator.ainvoke(initial_state)


async def ask_expert(claim_id: str, query: str, existing_state: dict | None = None) -> dict:
    """
    Invoke Agent H to answer an expert query about the current claim or policy.

    Args:
        claim_id:       Claim being consulted.
        query:          Natural-language question.
        existing_state: Optional partial state from a prior process_claim call.

    Returns:
        Updated extracted_data with h_result and h_sources.
    """
    state: ClaimState = {
        "claim_id": claim_id,
        "messages": [HumanMessage(content=query)],
        "status": ClaimStatus.OPEN,
        "extracted_data": {**(existing_state or {}), "h_query": query},
        "policy_check": existing_state.get("policy_check") if existing_state else None,
        "decision": existing_state.get("decision") if existing_state else None,
        "hitl_required": existing_state.get("hitl_required", False) if existing_state else False,
    }
    return await agent_h_node(state)
