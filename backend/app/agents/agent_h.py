"""
Agent H — RAG Conversational Assistant.

Answers natural-language questions from inspectors or lawyers about:
  - Policy coverage, deductibles, and exclusions
  - Required documents per claim type
  - Judicialization process (SP-PCS-022)
  - Due diligence obligations (PEPIN-POL-CP-0006)
  - Current case details

Shares the ChromaDB collection smart_claims_policies with Agent D.
"""
from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

from anthropic import AsyncAnthropic

from app.rag.retriever import get_coverage_retriever

if TYPE_CHECKING:
    from app.agents.orchestrator import ClaimState

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODEL = "claude-sonnet-4-20250514"
N_CONTEXT_CHUNKS = 5

_client: AsyncAnthropic | None = None


def _llm() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _client


_SYSTEM = """
Eres el Asistente Experto del sistema Smart-Claims de Seguros Pepín S.A.
Ayudas a inspectores de siniestros y abogados a consultar la política SP-PCS-009,
el proceso de reclamaciones PEPIN-PRD-LR-0001 y la política de debida diligencia
PEPIN-POL-CP-0006.

Reglas:
1. Responde siempre en español, de forma precisa y concisa.
2. Cita la sección exacta de la póliza cuando sea posible (ej: §2.1, R-SP-PCS-09-003).
3. Si la información no está en el contexto proporcionado, dilo claramente.
4. No inventes montos ni plazos — cita solo lo que está en los documentos.
5. Al final de tu respuesta, enumera las fuentes usadas.
""".strip()


async def answer_expert_query(state: "ClaimState") -> dict:
    """
    Answer a natural-language query about policy or current claim.

    Reads from state["extracted_data"]:
        h_query     str  — the question from the inspector/lawyer

    Also uses the current claim context (claim_type, policy_check, etc.) to
    enrich the response when relevant.

    Returns partial state update with:
        extracted_data.h_result    str   — the answer
        extracted_data.h_sources   list[str]  — source document names used
    """
    data: dict = state.get("extracted_data", {})
    query: str = data.get("h_query", "")

    if not query:
        return {
            "extracted_data": {
                **data,
                "h_result": "No se proporcionó ninguna consulta.",
                "h_sources": [],
            }
        }

    logger.info("[Agent H] Query for %s: %s", state["claim_id"], query[:80])

    # ── Retrieve relevant policy chunks ───────────────────────────────────────
    retriever = await get_coverage_retriever()
    context_chunks: list[dict] = []
    rag_context = ""

    if retriever is not None:
        context_chunks = retriever.query(query, n_results=N_CONTEXT_CHUNKS)
        rag_context = "\n---\n".join(c["document"] for c in context_chunks)

    sources = list({c["source"] for c in context_chunks})

    # ── Build current case summary for extra context ──────────────────────────
    policy: dict = state.get("policy_check") or {}
    case_ctx = json.dumps({
        "claim_id": state["claim_id"],
        "claim_type": data.get("claim_type", ""),
        "covered": policy.get("covered"),
        "net_payable_RD": policy.get("net_payable"),
        "decision": state.get("decision"),
        "hitl_required": state.get("hitl_required"),
        "f_judi_risk_level": data.get("f_judi_risk_level"),
        "g_fraud_score": data.get("g_fraud_score"),
    }, ensure_ascii=False)

    # ── Call Claude ───────────────────────────────────────────────────────────
    user_content = (
        f"**Pregunta:** {query}\n\n"
        f"**Contexto de la póliza:**\n{rag_context or 'No disponible — ChromaDB no conectado.'}\n\n"
        f"**Datos del expediente actual:**\n{case_ctx}"
    )

    try:
        resp = await _llm().messages.create(
            model=LLM_MODEL,
            max_tokens=1024,
            temperature=0,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        answer = resp.content[0].text.strip()
    except Exception as exc:
        logger.error("[Agent H] LLM failed: %s", exc)
        answer = f"Error al consultar el asistente: {exc}"

    logger.info("[Agent H] Answered %s (%d chars)", state["claim_id"], len(answer))

    return {
        "extracted_data": {
            **data,
            "h_result": answer,
            "h_sources": sources,
        }
    }
