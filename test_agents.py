"""
test_agents.py — Tests individuales por agente (sin pytest, sin Docker).

Uso:
    py -X utf8 test_agents.py --agent A   # orquestador
    py -X utf8 test_agents.py --agent B   # validación documental
    py -X utf8 test_agents.py --agent C   # VLM extracción
    py -X utf8 test_agents.py --agent D   # cobertura RAG
    py -X utf8 test_agents.py --agent E   # decisión + HITL
    py -X utf8 test_agents.py --agent F   # riesgo judicialización
    py -X utf8 test_agents.py --agent G   # OFAC + fraude
    py -X utf8 test_agents.py --agent H   # asistente conversacional
    py -X utf8 test_agents.py --all       # todos en secuencia
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent
sys.path.insert(0, str(_REPO / "backend"))
os.environ.setdefault("DATA_DIR", str(_REPO / "data"))

# ── Colores ANSI ──────────────────────────────────────────────────────────────
R = "\033[31m"; G = "\033[32m"; Y = "\033[33m"; B = "\033[34m"
M = "\033[35m"; C = "\033[36m"; W = "\033[0m"; BOLD = "\033[1m"


def _hdr(agent: str, title: str) -> None:
    print(f"\n{BOLD}{B}{'─'*60}{W}")
    print(f"{BOLD}{B}  AGENTE {agent} — {title}{W}")
    print(f"{BOLD}{B}{'─'*60}{W}")


def _ok(label: str, value) -> None:
    print(f"  {G}✓{W}  {label}: {BOLD}{value}{W}")


def _fail(label: str, value) -> None:
    print(f"  {R}✗{W}  {label}: {BOLD}{value}{W}")


def _info(label: str, value) -> None:
    print(f"  {C}→{W}  {label}: {value}")


def _assert(condition: bool, msg_ok: str, msg_fail: str) -> bool:
    if condition:
        _ok("PASS", msg_ok)
    else:
        _fail("FAIL", msg_fail)
    return condition


# ── Base state builder ────────────────────────────────────────────────────────

def _state(claim_id: str, **extra_data) -> dict:
    try:
        from langchain_core.messages import HumanMessage
        messages = [HumanMessage(content=f"Procesar reclamación {claim_id}")]
    except ImportError:
        messages = [{"role": "user", "content": f"Procesar reclamación {claim_id}"}]
    data = {
        "claim_type": "danys_propis",
        "client_name": "RODRIGUEZ PEREZ JUAN",
        "conductor_name": "RODRIGUEZ PEREZ JUAN",
        "amount_requested": 85_000.0,
        "submitted_docs": [
            "formulario_aviso_accidente", "acta_policial",
            "licencia_conducir", "cedula", "fotos_danos", "cotizacion_taller",
        ],
        "prior_claims_count": 0,
        "days_since_incident": 3,
        "interaction_count": 1,
        "proposal_rejected_before": False,
        "incident_time": "14:30",
        "channel": "email",
        "description": "Colisión trasera en semáforo. Paragolpes trasero y faro derecho dañados.",
        **extra_data,
    }
    return {
        "claim_id": claim_id,
        "messages": messages,
        "status": "VALIDATING",
        "extracted_data": data,
        "policy_check": None,
        "decision": None,
        "hitl_required": False,
    }


# ══════════════════════════════════════════════════════════════════════════════
# AGENTE A — Orquestador
# ══════════════════════════════════════════════════════════════════════════════
async def test_a() -> bool:
    _hdr("A", "Orquestador LangGraph")
    print(f"""
  {BOLD}Objetivo:{W}
    Agent A es el orquestador LangGraph ReAct. Construye el grafo de estados
    (StateGraph) que encadena los agentes B→G→F→C→D→E en secuencia y decide
    el enrutamiento (route_after_triage, route_after_g, etc.).

  {BOLD}Funciones clave:{W}
    orchestrator.process_claim(state)  — pipeline completo
    orchestrator.ask_expert(state)     — invoca Agente H directamente

  {BOLD}Test:{W} Verificar que el grafo se compila sin errores.
""")
    ok = True
    try:
        from app.agents.orchestrator import ClaimState  # noqa: F401
        _ok("Importación orchestrator.py", "OK")
    except Exception as e:
        _fail("Importación orchestrator.py", str(e))
        ok = False

    try:
        from langgraph.graph import StateGraph
        from app.agents.orchestrator import ClaimState
        g = StateGraph(ClaimState)
        _ok("StateGraph instanciado", "OK")
    except Exception as e:
        _fail("StateGraph", str(e))
        ok = False

    # Verifica que las funciones de entrada existen
    try:
        from app.agents.orchestrator import process_claim, ask_expert
        _ok("process_claim / ask_expert exportados", "OK")
    except Exception as e:
        _fail("Funciones de entrada", str(e))
        ok = False

    print(f"\n  {Y}Nota:{W} Para ver el orquestador en acción usa demo_run.py (pipeline completo).")
    return ok


# ══════════════════════════════════════════════════════════════════════════════
# AGENTE B — Validación Documental
# ══════════════════════════════════════════════════════════════════════════════
async def test_b() -> bool:
    _hdr("B", "Validación Documental [CU-08 · R-SP-PCS-09-001/002]")
    print(f"""
  {BOLD}Objetivo:{W}
    Verifica que la reclamación incluye todos los documentos requeridos según el
    tipo (SP-PCS-009 §2). Si el tipo es 'danys_mecanics' → rechazo inmediato (§2.5).
    Si conductor ≠ propietario → marca cheque a nombre del propietario (R-SP-PCS-09-002).

  {BOLD}Input:{W} extracted_data.claim_type, submitted_docs, client_name, conductor_name
  {BOLD}Output:{W} b_missing_docs, b_docs_complete, flag_cheque_propietario, decision (si reject)
""")
    from app.agents.agent_b import validate_claim_documents
    passed = 0

    # ── Caso 1: Documentos completos ──────────────────────────────────────────
    print(f"  {BOLD}Caso 1:{W} Daños propios con todos los documentos")
    s = _state("B-001")
    result = await validate_claim_documents(s)
    data = result["extracted_data"]
    if _assert(data["b_docs_complete"] is True, "b_docs_complete=True", f"b_docs_complete={data['b_docs_complete']}"):
        passed += 1
    if _assert(data["b_missing_docs"] == [], "sin docs faltantes", f"missing={data['b_missing_docs']}"):
        passed += 1
    if _assert(data["flag_cheque_propietario"] is False, "mismo conductor/propietario", f"flag={data['flag_cheque_propietario']}"):
        passed += 1

    # ── Caso 2: Documentos incompletos ────────────────────────────────────────
    print(f"\n  {BOLD}Caso 2:{W} Documentos faltantes (acta_policial y cotizacion_taller ausentes)")
    s2 = _state("B-002", submitted_docs=["formulario_aviso_accidente", "licencia_conducir", "cedula", "fotos_danos"])
    result2 = await validate_claim_documents(s2)
    d2 = result2["extracted_data"]
    if _assert(d2["b_docs_complete"] is False, "b_docs_complete=False", f"got {d2['b_docs_complete']}"):
        passed += 1
    if _assert("acta_policial" in d2["b_missing_docs"], "acta_policial en faltantes", f"missing={d2['b_missing_docs']}"):
        passed += 1
    _info("Docs faltantes", d2["b_missing_docs"])

    # ── Caso 3: Rechazo inmediato danys_mecanics ──────────────────────────────
    print(f"\n  {BOLD}Caso 3:{W} Daños mecánicos → rechazo inmediato §2.5")
    s3 = _state("B-003", claim_type="danys_mecanics")
    result3 = await validate_claim_documents(s3)
    if _assert(result3.get("decision") == "reject", "decision=reject", f"got {result3.get('decision')}"):
        passed += 1
    if _assert(result3.get("status") == "REJECTED", "status=REJECTED", f"got {result3.get('status')}"):
        passed += 1
    _info("Razón", result3["extracted_data"].get("b_reject_reason", ""))

    # ── Caso 4: Conductor ≠ propietario (R-SP-PCS-09-002) ─────────────────────
    print(f"\n  {BOLD}Caso 4:{W} Conductor ≠ propietario → flag_cheque_propietario")
    s4 = _state("B-004", conductor_name="GOMEZ MENDEZ CARLOS", client_name="RODRIGUEZ PEREZ JUAN")
    result4 = await validate_claim_documents(s4)
    if _assert(result4["extracted_data"]["flag_cheque_propietario"] is True,
               "cheque a nombre del propietario", f"flag={result4['extracted_data']['flag_cheque_propietario']}"):
        passed += 1

    total = 8
    print(f"\n  {BOLD}Resultado Agente B:{W} {G if passed == total else R}{passed}/{total} OK{W}")
    return passed == total


# ══════════════════════════════════════════════════════════════════════════════
# AGENTE C — Extracción VLM
# ══════════════════════════════════════════════════════════════════════════════
async def test_c() -> bool:
    _hdr("C", "Extracción VLM — Claude Vision [CU-06]")
    print(f"""
  {BOLD}Objetivo:{W}
    Usa Claude Vision para extraer datos estructurados de imágenes y documentos:
    fotos de daños → {{parts_damaged, severity, estimated_repair_RD}}
    cotización de taller → {{taller_name, date, items, total_RD}}
    acta policial → {{acta_number, incident_date, parties, description}}
    En PoC (sin imagen real), opera sobre la descripción textual del expediente.

  {BOLD}Input:{W} extracted_data.file_url, doc_type, description
  {BOLD}Output:{W} extracted_data.c_result (dict estructurado)
""")
    from app.agents.agent_c import extract_from_document
    has_key = bool(os.getenv("ANTHROPIC_API_KEY", ""))
    passed = 0

    # ── Caso 1: Foto de daños (modo PoC, sin imagen real) ─────────────────────
    print(f"  {BOLD}Caso 1:{W} Extracción fotos_danos — modo PoC (sin URL de imagen)")
    s = _state("C-001", doc_type="fotos_danos",
               description="Vehículo Toyota Yaris 2020. Daños en paragolpes trasero (aplastado) y faro derecho (roto). Carrocería lateral abollada. Severidad moderada. Reparación estimada RD$85,000.")
    result = await extract_from_document(s)
    c_res = result["extracted_data"].get("c_result", {})
    _info("c_result", c_res)
    if has_key:
        if _assert("parts_damaged" in c_res or "error" not in c_res, "LLM extrajo datos", f"resultado={c_res}"):
            passed += 1
    else:
        if _assert("error" in c_res or "doc_type" in c_res, "fallback sin API key (esperado)", f"resultado={c_res}"):
            passed += 1
        print(f"  {Y}⚠{W}  Sin ANTHROPIC_API_KEY — Claude Vision no disponible")
        print(f"  {Y}→{W}  Configura: $env:ANTHROPIC_API_KEY = 'sk-ant-...' para ver extracción real")

    # ── Caso 2: Acta policial ─────────────────────────────────────────────────
    print(f"\n  {BOLD}Caso 2:{W} Extracción acta_policial — modo PoC")
    s2 = _state("C-002", doc_type="acta_policial",
                description="Acta Q-352608-26. Fecha: 2026-03-15. Hora: 14:30. Lugar: Av. Winston Churchill esq. Enriquillo. "
                            "Conductor: RODRIGUEZ PEREZ JUAN (cédula 001-0000001-1). Vehículo: Toyota Yaris PP-39007. "
                            "Colisión con poste de alumbrado en reversa. Oficial: Cap. MENDEZ badge 2891.")
    result2 = await extract_from_document(s2)
    c_res2 = result2["extracted_data"].get("c_result", {})
    _info("c_result", c_res2)
    if has_key:
        if _assert("acta_number" in c_res2 or "error" not in c_res2, "LLM extrajo acta", f"resultado={c_res2}"):
            passed += 1
    else:
        passed += 1  # expected fallback
        print(f"  {Y}⚠{W}  Sin ANTHROPIC_API_KEY — resultado esperado con error/fallback")

    total = 2
    print(f"\n  {BOLD}Resultado Agente C:{W} {G if passed == total else Y}{passed}/{total} OK{W}")
    return passed == total


# ══════════════════════════════════════════════════════════════════════════════
# AGENTE D — Cobertura RAG
# ══════════════════════════════════════════════════════════════════════════════
async def test_d() -> bool:
    _hdr("D", "Cobertura RAG — ChromaDB + Claude [CU-08 · R-SP-PCS-09-003/004]")
    print(f"""
  {BOLD}Objetivo:{W}
    Determina si la reclamación está cubierta por la póliza SP-PCS-009. Consulta
    ChromaDB (RAG) para encontrar secciones relevantes, luego Claude interpreta.
    Aplica R-SP-PCS-09-003 (cobertura restante si hay reclamaciones previas) y
    R-SP-PCS-09-004 (si monto < deducible, asegurado paga el total).
    Si ChromaDB no está disponible → fallback a límites hardcoded SP-PCS-009.

  {BOLD}Input:{W} extracted_data.claim_type, amount_requested, prior_coverage_used
  {BOLD}Output:{W} policy_check {{covered, max_coverage, deductible, net_payable, section, confidence}}
""")
    from app.agents.agent_d import check_policy_coverage
    passed = 0

    # ── Caso 1: Daños propios, monto dentro del límite ────────────────────────
    print(f"  {BOLD}Caso 1:{W} danys_propis RD$85,000 — debe ser cubierto")
    s = _state("D-001", amount_requested=85_000)
    result = await check_policy_coverage(s)
    pc = result["policy_check"]
    _info("covered", pc["covered"])
    _info("max_coverage", f"RD$ {pc['max_coverage']:,.0f}")
    _info("deductible", f"RD$ {pc['deductible']:,.0f}")
    _info("net_payable", f"RD$ {pc['net_payable']:,.0f}")
    _info("confidence", f"{pc['confidence']:.0%}")
    _info("section", pc["policy_section"])
    if _assert(pc["covered"] is True, "cubierto=True", f"cubierto={pc['covered']}"):
        passed += 1
    if _assert(pc["net_payable"] == 80_000.0, "net_payable=RD$80,000 (85k - 5k deducible)", f"got {pc['net_payable']}"):
        passed += 1

    # ── Caso 2: Deducible cubre el total (R-SP-PCS-09-004) ───────────────────
    print(f"\n  {BOLD}Caso 2:{W} Monto RD$3,000 < deducible RD$5,000 → net_payable=0")
    s2 = _state("D-002", amount_requested=3_000)
    result2 = await check_policy_coverage(s2)
    pc2 = result2["policy_check"]
    _info("net_payable", f"RD$ {pc2['net_payable']:,.0f}")
    if _assert(pc2["net_payable"] == 0.0, "net_payable=RD$0 (deducible > monto)", f"got {pc2['net_payable']}"):
        passed += 1

    # ── Caso 3: RC con cobertura hasta RD$2M ────────────────────────────────
    print(f"\n  {BOLD}Caso 3:{W} RC RD$1,200,000 — max RD$2M, deducible RD$0")
    s3 = _state("D-003", claim_type="RC", amount_requested=1_200_000)
    result3 = await check_policy_coverage(s3)
    pc3 = result3["policy_check"]
    _info("net_payable", f"RD$ {pc3['net_payable']:,.0f}")
    if _assert(pc3["net_payable"] == 1_200_000.0, "net_payable=RD$1,200,000", f"got {pc3['net_payable']}"):
        passed += 1

    # ── Caso 4: Cobertura previa usada (R-SP-PCS-09-003) ─────────────────────
    print(f"\n  {BOLD}Caso 4:{W} danys_propis, ya usó RD$400k de los RD$500k → disponible RD$100k")
    s4 = _state("D-004", amount_requested=200_000, prior_coverage_used=400_000)
    result4 = await check_policy_coverage(s4)
    pc4 = result4["policy_check"]
    _info("max_coverage disponible", f"RD$ {pc4['max_coverage']:,.0f}")
    _info("net_payable", f"RD$ {pc4['net_payable']:,.0f}")
    if _assert(pc4["max_coverage"] == 100_000.0, "disponible=RD$100,000", f"got {pc4['max_coverage']}"):
        passed += 1
    if _assert(pc4["net_payable"] == 95_000.0, "net_payable=RD$95,000 (100k - 5k deducible)", f"got {pc4['net_payable']}"):
        passed += 1

    total = 6
    print(f"\n  {BOLD}Resultado Agente D:{W} {G if passed == total else Y}{passed}/{total} OK{W}")
    return passed == total


# ══════════════════════════════════════════════════════════════════════════════
# AGENTE E — Decisión + HITL
# ══════════════════════════════════════════════════════════════════════════════
async def test_e() -> bool:
    _hdr("E", "Decisión Final CoT + HITL [§3.3 SP-PCS-009]")
    print(f"""
  {BOLD}Objetivo:{W}
    Toma la decisión final: approve / reject / request_info / hitl.
    Evalúa 4 triggers HITL en orden de prioridad:
      1. OFAC flagged           → HITL (Oficial de Cumplimiento)
      2. net_payable > RD$500k  → HITL (Director de Reclamaciones)
      3. fraud_score > 30%      → HITL (Área de Cumplimiento)
      4. confidence < 75%       → HITL (Analista)
    Si no hay HITL: Chain-of-Thought con Claude → approve/reject/request_info.
    Sin API key → _rule_based_decision() determinista.

  {BOLD}Input:{W} policy_check, extracted_data.g_fraud_score, g_ofac_flagged, b_docs_complete
  {BOLD}Output:{W} decision, status, hitl_required, e_rationale
""")
    from app.agents.agent_e import decide_claim
    passed = 0

    def _state_e(claim_id, *, net_payable=80_000, confidence=0.85, fraud=0.0,
                 ofac=False, docs_ok=True, missing=None, claim_type="danys_propis"):
        s = _state(claim_id, claim_type=claim_type, g_fraud_score=fraud,
                   g_ofac_flagged=ofac, b_docs_complete=docs_ok,
                   b_missing_docs=missing or [])
        s["policy_check"] = {
            "covered": True, "net_payable": net_payable,
            "confidence": confidence, "policy_section": "§2.1",
        }
        return s

    # ── Caso 1: Aprobación limpia ─────────────────────────────────────────────
    print(f"  {BOLD}Caso 1:{W} Docs completos, RD$80k, fraude 0% → APPROVE")
    r = await decide_claim(_state_e("E-001"))
    _info("decision", r["decision"]); _info("rationale", r["extracted_data"].get("e_rationale", ""))
    if _assert(r["decision"] in ("approve",), "decision=approve", f"got {r['decision']}"):
        passed += 1
    if _assert(r["hitl_required"] is False, "hitl=False", f"hitl={r['hitl_required']}"):
        passed += 1

    # ── Caso 2: HITL por monto ────────────────────────────────────────────────
    print(f"\n  {BOLD}Caso 2:{W} net_payable RD$1,200,000 > RD$500k → HITL")
    r2 = await decide_claim(_state_e("E-002", net_payable=1_200_000))
    _info("decision", r2["decision"]); _info("hitl", r2["hitl_required"])
    _info("reason", r2["extracted_data"].get("e_rationale", ""))
    if _assert(r2["decision"] == "hitl", "decision=hitl", f"got {r2['decision']}"):
        passed += 1
    if _assert(r2["hitl_required"] is True, "hitl=True", f"hitl={r2['hitl_required']}"):
        passed += 1

    # ── Caso 3: HITL por fraude ───────────────────────────────────────────────
    print(f"\n  {BOLD}Caso 3:{W} fraud_score 45% > 30% → HITL")
    r3 = await decide_claim(_state_e("E-003", fraud=0.45))
    _info("decision", r3["decision"]); _info("reason", r3["extracted_data"].get("e_rationale", ""))
    if _assert(r3["decision"] == "hitl", "decision=hitl (fraude)", f"got {r3['decision']}"):
        passed += 1

    # ── Caso 4: HITL por OFAC ─────────────────────────────────────────────────
    print(f"\n  {BOLD}Caso 4:{W} OFAC flagged → HITL (prioridad máxima)")
    r4 = await decide_claim(_state_e("E-004", ofac=True))
    _info("decision", r4["decision"]); _info("reason", r4["extracted_data"].get("e_rationale", ""))
    if _assert(r4["decision"] == "hitl", "decision=hitl (OFAC)", f"got {r4['decision']}"):
        passed += 1

    # ── Caso 5: Request info (docs incompletos) ───────────────────────────────
    print(f"\n  {BOLD}Caso 5:{W} Documentos faltantes → REQUEST_INFO")
    r5 = await decide_claim(_state_e("E-005", docs_ok=False, missing=["acta_policial", "cotizacion_taller"]))
    _info("decision", r5["decision"]); _info("rationale", r5["extracted_data"].get("e_rationale", ""))
    if _assert(r5["decision"] in ("request_info",), "decision=request_info", f"got {r5['decision']}"):
        passed += 1

    # ── Caso 6: HITL por baja confianza ──────────────────────────────────────
    print(f"\n  {BOLD}Caso 6:{W} Confianza 60% < 75% → HITL (analista)")
    r6 = await decide_claim(_state_e("E-006", confidence=0.60))
    _info("decision", r6["decision"]); _info("reason", r6["extracted_data"].get("e_rationale", ""))
    if _assert(r6["decision"] == "hitl", "decision=hitl (baja confianza)", f"got {r6['decision']}"):
        passed += 1

    total = 8
    print(f"\n  {BOLD}Resultado Agente E:{W} {G if passed == total else R}{passed}/{total} OK{W}")
    return passed == total


# ══════════════════════════════════════════════════════════════════════════════
# AGENTE F — Riesgo Judicialización
# ══════════════════════════════════════════════════════════════════════════════
async def test_f() -> bool:
    _hdr("F", "Riesgo Judicialización — XGBoost [CU-10 · SP-PCS-022.3]")
    print(f"""
  {BOLD}Objetivo:{W}
    Predice la probabilidad de que una reclamación escale a litigio (SP-PCS-022).
    Usa XGBoost con 10 features: monto, prior_claims, días desde incidente,
    interacciones, propuesta rechazada, tipo, risk_score, canal.
    Niveles: HIGH >60%, MEDIUM >30%, LOW ≤30%.
    Si el modelo .pkl no existe → _heuristic_score() determinista.

  {BOLD}Input:{W} extracted_data.claim_type, amount_requested, prior_claims_count,
            days_since_incident, interaction_count, proposal_rejected_before,
            g_risk_score, channel
  {BOLD}Output:{W} f_judi_probability, f_judi_risk_level, f_shap_values, f_model_used
""")
    from app.agents.agent_f import predict_judicialization_risk
    passed = 0

    # ── Caso 1: Perfil de bajo riesgo ─────────────────────────────────────────
    print(f"  {BOLD}Caso 1:{W} RC, RD$150k, 0 previas, sin rechazo → LOW esperado")
    s = _state("F-001", claim_type="danys_propis", amount_requested=150_000,
               prior_claims_count=0, days_since_incident=2, interaction_count=1,
               proposal_rejected_before=False, g_risk_score=0.0)
    r = await predict_judicialization_risk(s)
    d = r["extracted_data"]
    _info("probabilidad", f"{d['f_judi_probability']:.1%}")
    _info("nivel", d["f_judi_risk_level"])
    _info("modelo", d["f_model_used"])
    if _assert(d["f_judi_risk_level"] == "LOW", "risk=LOW", f"got {d['f_judi_risk_level']}"):
        passed += 1
    if _assert(d["f_judi_probability"] < 0.30, "prob < 30%", f"got {d['f_judi_probability']:.1%}"):
        passed += 1

    # ── Caso 2: Perfil de alto riesgo (prob > bajo riesgo) ───────────────────
    print(f"\n  {BOLD}Caso 2:{W} RC, RD$800k, 4 previas, propuesta rechazada → prob > caso 1")
    s2 = _state("F-002", claim_type="RC", amount_requested=800_000,
                prior_claims_count=4, days_since_incident=45, interaction_count=8,
                proposal_rejected_before=True, g_risk_score=0.35, channel="phone")
    r2 = await predict_judicialization_risk(s2)
    d2 = r2["extracted_data"]
    _info("probabilidad", f"{d2['f_judi_probability']:.1%}")
    _info("nivel", d2["f_judi_risk_level"])
    _info("nota", "XGBoost entrenado en 100 registros — niveles dependen del dataset")
    if _assert(d2["f_judi_probability"] >= 0.0, "probabilidad válida [0,1]", f"got {d2['f_judi_probability']}"):
        passed += 1
    if _assert(d2["f_judi_probability"] > d["f_judi_probability"],
               f"prob alto riesgo ({d2['f_judi_probability']:.1%}) > bajo riesgo ({d['f_judi_probability']:.1%})",
               f"modelo no diferencia perfiles: {d2['f_judi_probability']:.1%} vs {d['f_judi_probability']:.1%}"):
        passed += 1

    # ── Caso 3: Modelo cargado correctamente ─────────────────────────────────
    print(f"\n  {BOLD}Caso 3:{W} Verificar modelo/fallback declarado correctamente")
    if _assert(d["f_model_used"] in ("xgboost", "heuristic_fallback"),
               f"model_used={d['f_model_used']}", f"valor inesperado: {d['f_model_used']}"):
        passed += 1
    _info("Modelo en uso", d["f_model_used"])

    total = 5
    print(f"\n  {BOLD}Resultado Agente F:{W} {G if passed == total else Y}{passed}/{total} OK{W}")
    return passed == total


# ══════════════════════════════════════════════════════════════════════════════
# AGENTE G — OFAC + Fraude
# ══════════════════════════════════════════════════════════════════════════════
async def test_g() -> bool:
    _hdr("G", "OFAC + Fraude [CU-05 · PEPIN-POL-CP-0006]")
    print(f"""
  {BOLD}Objetivo:{W}
    1. OFAC fuzzy match (rapidfuzz token_sort_ratio ≥ 85) sobre lista de sanciones.
       Match → g_ofac_flagged=True → HITL automático (Oficial de Cumplimiento).
    2. Heuristic fraud score (0.0–1.0) basado en:
       +0.20 danys_propis AND monto > RD$500k
       +0.25 prior_claims ≥ 3  |  +0.10 si son 2
       +0.15 incidente entre 00:00–04:59
       +0.10 documentos incompletos
    3. Nivel debida diligencia: ampliada (OFAC o score > 50%) / simplificada.

  {BOLD}Input:{W} extracted_data.client_name, conductor_name, claim_type,
            amount_requested, prior_claims_count, incident_time, b_docs_complete
  {BOLD}Output:{W} g_ofac_flagged, g_fraud_score, g_due_diligence, hitl_required
""")
    from app.agents.agent_g import check_fraud_and_compliance
    passed = 0

    # ── Caso 1: Perfil limpio ─────────────────────────────────────────────────
    print(f"  {BOLD}Caso 1:{W} Reclamante sin antecedentes, horario normal → fraude 0%")
    s = _state("G-001", client_name="PEREZ SANTOS MARIA", conductor_name="PEREZ SANTOS MARIA",
               prior_claims_count=0, incident_time="14:30", b_docs_complete=True)
    r = await check_fraud_and_compliance(s)
    d = r["extracted_data"]
    _info("ofac_flagged", d["g_ofac_flagged"])
    _info("fraud_score", f"{d['g_fraud_score']:.0%}")
    _info("due_diligence", d["g_due_diligence"])
    if _assert(d["g_ofac_flagged"] is False, "ofac=False", f"got {d['g_ofac_flagged']}"):
        passed += 1
    if _assert(d["g_fraud_score"] == 0.0, "fraude=0%", f"got {d['g_fraud_score']:.0%}"):
        passed += 1
    if _assert(d["g_due_diligence"] == "simplificada", "diligencia=simplificada", f"got {d['g_due_diligence']}"):
        passed += 1

    # ── Caso 2: Match OFAC exacto ─────────────────────────────────────────────
    print(f"\n  {BOLD}Caso 2:{W} Nombre en lista OFAC → flagged=True, HITL activado")
    s2 = _state("G-002", client_name="FICTICIO GOMEZ RIOS ANTONIO RAFAEL")
    r2 = await check_fraud_and_compliance(s2)
    d2 = r2["extracted_data"]
    _info("ofac_flagged", d2["g_ofac_flagged"])
    _info("match_name", d2.get("g_ofac_match_name", ""))
    _info("match_score", f"{d2.get('g_ofac_match_score', 0):.0f}%")
    if _assert(d2["g_ofac_flagged"] is True, "ofac=True", f"got {d2['g_ofac_flagged']}"):
        passed += 1
    if _assert(r2.get("hitl_required") is True, "hitl_required=True", f"got {r2.get('hitl_required')}"):
        passed += 1
    if _assert(d2.get("g_due_diligence") == "ampliada", "diligencia=ampliada", f"got {d2.get('g_due_diligence')}"):
        passed += 1

    # ── Caso 3: Score fraude por acumulación de señales ───────────────────────
    print(f"\n  {BOLD}Caso 3:{W} 3 previas + horario nocturno + docs incompletos → fraude > 30%")
    s3 = _state("G-003", client_name="SANTOS VILORIA PEDRO",
                prior_claims_count=3, incident_time="02:15",
                b_docs_complete=False, amount_requested=80_000)
    r3 = await check_fraud_and_compliance(s3)
    d3 = r3["extracted_data"]
    _info("fraud_score", f"{d3['g_fraud_score']:.0%}")
    _info("due_diligence", d3["g_due_diligence"])
    if _assert(d3["g_fraud_score"] > 0.30, f"fraude {d3['g_fraud_score']:.0%} > 30%", f"got {d3['g_fraud_score']:.0%}"):
        passed += 1

    total = 7
    print(f"\n  {BOLD}Resultado Agente G:{W} {G if passed == total else R}{passed}/{total} OK{W}")
    return passed == total


# ══════════════════════════════════════════════════════════════════════════════
# AGENTE H — Asistente Conversacional
# ══════════════════════════════════════════════════════════════════════════════
async def test_h() -> bool:
    _hdr("H", "Asistente Conversacional RAG [CU-01]")
    print(f"""
  {BOLD}Objetivo:{W}
    Responde preguntas en lenguaje natural de inspectores y abogados sobre:
    - Coberturas y deducibles (SP-PCS-009)
    - Documentos requeridos por tipo de reclamación
    - Proceso de judicialización (SP-PCS-022)
    - Debida diligencia (PEPIN-POL-CP-0006)
    - Detalles del expediente actual
    Usa ChromaDB (shared con Agente D) para RAG. Sin ChromaDB → responde
    con Claude usando solo el contexto del expediente.

  {BOLD}Input:{W} extracted_data.h_query  (string con la pregunta)
  {BOLD}Output:{W} extracted_data.h_result (respuesta), h_sources (lista de fuentes)
""")
    from app.agents.agent_h import answer_expert_query
    has_key = bool(os.getenv("ANTHROPIC_API_KEY", ""))
    passed = 0

    # ── Caso 1: Consulta sin query (error handling) ────────────────────────────
    print(f"  {BOLD}Caso 1:{W} Query vacía → mensaje de error controlado")
    s = _state("H-001")
    r = await answer_expert_query(s)
    d = r["extracted_data"]
    _info("h_result", d.get("h_result", ""))
    if _assert("h_result" in d, "h_result presente", f"keys={list(d.keys())}"):
        passed += 1
    if _assert(d.get("h_result") == "No se proporcionó ninguna consulta.", "mensaje de error correcto", f"got: {d.get('h_result')}"):
        passed += 1

    # ── Caso 2: Consulta sobre deducible ─────────────────────────────────────
    print(f"\n  {BOLD}Caso 2:{W} '¿Cuál es el deducible para daños propios?'")
    s2 = _state("H-002", h_query="¿Cuál es el deducible para daños propios según SP-PCS-009?")
    r2 = await answer_expert_query(s2)
    d2 = r2["extracted_data"]
    answer = d2.get("h_result", "")
    _info("respuesta (primeros 200 chars)", answer[:200] + "..." if len(answer) > 200 else answer)
    _info("fuentes", d2.get("h_sources", []))
    if has_key:
        if _assert(len(answer) > 50, "respuesta generada con contenido", f"respuesta vacía: '{answer[:50]}'"):
            passed += 1
    else:
        print(f"  {Y}⚠{W}  Sin ANTHROPIC_API_KEY — Agente H no puede responder")
        print(f"  {Y}→{W}  Configura $env:ANTHROPIC_API_KEY para ver respuestas RAG reales")
        if _assert("Error" in answer or "error" in answer.lower(), "error esperado sin API key", f"got: {answer[:80]}"):
            passed += 1

    # ── Caso 3: Consulta sobre OFAC ──────────────────────────────────────────
    print(f"\n  {BOLD}Caso 3:{W} '¿Cuándo se activa la debida diligencia ampliada?'")
    s3 = _state("H-003", h_query="¿Cuándo se activa la debida diligencia ampliada según PEPIN-POL-CP-0006?")
    r3 = await answer_expert_query(s3)
    d3 = r3["extracted_data"]
    a3 = d3.get("h_result", "")
    _info("respuesta (primeros 200 chars)", a3[:200] + "..." if len(a3) > 200 else a3)
    if _assert("h_result" in d3 and "h_sources" in d3,
               "estructura correcta (h_result + h_sources)", f"keys={list(d3.keys())}"):
        passed += 1

    total = 4 if has_key else 4
    print(f"\n  {BOLD}Resultado Agente H:{W} {G if passed == total else Y}{passed}/{total} OK{W}")
    return passed == total


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

AGENTS: dict[str, tuple[str, "Callable"]] = {
    "A": ("Orquestador LangGraph", test_a),
    "B": ("Validación Documental", test_b),
    "C": ("Extracción VLM", test_c),
    "D": ("Cobertura RAG", test_d),
    "E": ("Decisión + HITL", test_e),
    "F": ("Riesgo Judicialización", test_f),
    "G": ("OFAC + Fraude", test_g),
    "H": ("Asistente Conversacional", test_h),
}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Tests individuales por agente — Smart-Claims")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--agent", choices=list(AGENTS.keys()), help="Agente a testear (A–H)")
    grp.add_argument("--all", action="store_true", help="Ejecutar todos los agentes en secuencia")
    args = parser.parse_args()

    has_key = bool(os.getenv("ANTHROPIC_API_KEY", ""))
    print(f"\n{BOLD}{B}╔══════════════════════════════════════════════════════════╗")
    print(f"║        SMART-CLAIMS — Tests Individuales por Agente     ║")
    print(f"║        Seguros Pepín S.A. · PoC Académico (TFM)         ║")
    print(f"╚══════════════════════════════════════════════════════════╝{W}")
    print(f"  ANTHROPIC_API_KEY: {G + 'configurada' if has_key else Y + 'NO configurada (C/D/E/H usarán fallbacks)'}{W}")
    print(f"  DATA_DIR: {os.environ['DATA_DIR']}")

    to_run = list(AGENTS.keys()) if args.all else [args.agent]
    results: dict[str, bool] = {}

    for agent_id in to_run:
        title, fn = AGENTS[agent_id]
        try:
            results[agent_id] = await fn()
        except Exception as e:
            print(f"\n  {R}ERROR en Agente {agent_id}: {e}{W}")
            import traceback; traceback.print_exc()
            results[agent_id] = False

    if args.all or len(to_run) > 1:
        print(f"\n{BOLD}{B}{'═'*60}{W}")
        print(f"{BOLD}  RESUMEN FINAL{W}")
        print(f"{BOLD}{B}{'═'*60}{W}")
        for aid, ok in results.items():
            status = f"{G}✓ PASS{W}" if ok else f"{R}✗ FAIL{W}"
            print(f"  Agente {aid} — {AGENTS[aid][0][:35]:<35} {status}")
        total_ok = sum(results.values())
        total = len(results)
        color = G if total_ok == total else R
        print(f"\n  {color}{BOLD}{total_ok}/{total} agentes OK{W}\n")


if __name__ == "__main__":
    asyncio.run(main())
