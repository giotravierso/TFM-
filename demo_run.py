"""
Smart-Claims Agent — Demo interactivo end-to-end.

Encadena todos los agentes (B → G → F → C → D → E) sobre una reclamación
de ejemplo, sin necesidad de FastAPI, MariaDB ni Docker.

Uso:
    python demo_run.py                          # escenario interactivo
    python demo_run.py --scenario 1             # aprobación automática
    python demo_run.py --scenario 2             # HITL por monto alto
    python demo_run.py --scenario 3             # rechazo (danys_mecanics)
    python demo_run.py --scenario 4             # solicitud info (docs incompletos)
    python demo_run.py --scenario 5             # HITL por OFAC

Requiere:
    pip install rapidfuzz xgboost scikit-learn pandas numpy anthropic
    DATA_DIR debe apuntar a smart-claims-agent/data/  (se configura automático)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import argparse
from datetime import datetime
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent
sys.path.insert(0, str(_REPO / "backend"))
os.environ.setdefault("DATA_DIR", str(_REPO / "data"))

# ── Color helpers (ANSI — funciona en Windows Terminal y VSCode) ──────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
BLUE   = "\033[34m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
PURPLE = "\033[35m"
DIM    = "\033[2m"


def hdr(agent: str, cu: str = "") -> str:
    tag = f"  {DIM}[{cu}]{RESET}" if cu else ""
    return f"\n{BOLD}{BLUE}{'─'*60}{RESET}\n{BOLD}{BLUE}  {agent}{RESET}{tag}\n{BLUE}{'─'*60}{RESET}"


def ok(msg: str)   -> None: print(f"  {GREEN}✓{RESET}  {msg}")
def warn(msg: str) -> None: print(f"  {YELLOW}⚠{RESET}  {msg}")
def err(msg: str)  -> None: print(f"  {RED}✗{RESET}  {msg}")
def info(msg: str) -> None: print(f"  {CYAN}→{RESET}  {msg}")
def kv(k: str, v)  -> None: print(f"  {DIM}{k:<26}{RESET}{BOLD}{v}{RESET}")


def banner() -> None:
    print(f"""
{BOLD}{BLUE}╔══════════════════════════════════════════════════════════╗
║        SMART-CLAIMS AGENT — Demo End-to-End              ║
║        Seguros Pepín S.A. · PoC Académico (TFM)          ║
╚══════════════════════════════════════════════════════════╝{RESET}
""")


# ── Escenarios predefinidos ────────────────────────────────────────────────────

SCENARIOS: dict[int, dict] = {
    1: {
        "name": "Aprobación automática — Daños propios completos",
        "state": {
            "claim_id": "EXP-2026-DEMO-001",
            "claim_type": "danys_propis",
            "client_name": "PEREZ GARCIA JUAN MANUEL",
            "conductor_name": "PEREZ GARCIA JUAN MANUEL",
            "amount_requested": 85_000,
            "submitted_docs": [
                "formulario_aviso_accidente", "acta_policial",
                "licencia_conducir", "cedula",
                "fotos_danos", "cotizacion_taller",
            ],
            "prior_claims_count": 0,
            "days_since_incident": 2,
            "incident_time": "14:30",
            "interaction_count": 1,
            "proposal_rejected_before": False,
            "channel": "email",
            "description": "Colisión trasera en estacionamiento del Centro León, Santiago.",
        },
    },
    2: {
        "name": "HITL por monto alto — RC supera RD$500.000",
        "state": {
            "claim_id": "EXP-2026-DEMO-002",
            "claim_type": "RC",
            "client_name": "JIMENEZ PAREDES HECTOR RAFAEL",
            "conductor_name": "JIMENEZ PAREDES HECTOR RAFAEL",
            "amount_requested": 1_250_000,
            "submitted_docs": [
                "aviso_siniestro", "acta_policial",
                "cedula", "licencia_conducir", "fotos_danos",
            ],
            "prior_claims_count": 0,
            "days_since_incident": 5,
            "incident_time": "11:15",
            "interaction_count": 2,
            "proposal_rejected_before": False,
            "channel": "presencial",
            "description": "Choque múltiple en autopista Duarte km 14. Responsabilidad civil por daños a terceros.",
        },
    },
    3: {
        "name": "Rechazo inmediato — Daños mecánicos (§2.5 no cubierto)",
        "state": {
            "claim_id": "EXP-2026-DEMO-003",
            "claim_type": "danys_mecanics",
            "client_name": "SANTOS ROJAS MARIA ELENA",
            "conductor_name": "SANTOS ROJAS MARIA ELENA",
            "amount_requested": 45_000,
            "submitted_docs": [],
            "prior_claims_count": 1,
            "days_since_incident": 3,
            "incident_time": "09:00",
            "interaction_count": 1,
            "proposal_rejected_before": False,
            "channel": "phone",
            "description": "Fallo del motor por desgaste. Solicita cobertura por reparación mecánica.",
        },
    },
    4: {
        "name": "Solicitud de información — Documentos incompletos",
        "state": {
            "claim_id": "EXP-2026-DEMO-004",
            "claim_type": "danys_propis",
            "client_name": "MORALES RUIZ PABLO ANDRES",
            "conductor_name": "MORALES RUIZ PABLO ANDRES",
            "amount_requested": 120_000,
            "submitted_docs": [
                "cedula", "licencia_conducir", "fotos_danos",
                # Faltan: formulario_aviso_accidente, acta_policial, cotizacion_taller
            ],
            "prior_claims_count": 1,
            "days_since_incident": 4,
            "incident_time": "16:45",
            "interaction_count": 1,
            "proposal_rejected_before": False,
            "channel": "email",
            "description": "Impacto lateral con semáforo en la Av. Winston Churchill.",
        },
    },
    5: {
        "name": "HITL por OFAC — Coincidencia en lista de sanciones",
        "state": {
            "claim_id": "EXP-2026-DEMO-005",
            "claim_type": "DPA",
            "client_name": "FICTICIO GOMEZ RIOS ANTONIO RAFAEL",
            "conductor_name": "FICTICIO GOMEZ RIOS ANTONIO RAFAEL",
            "amount_requested": 320_000,
            "submitted_docs": [
                "aviso_siniestro", "acta_policial_certificada",
                "acta_conciliacion", "presupuesto_piezas",
                "fotos_danos_con_placa", "matricula",
                "cedula", "licencia_conducir",
            ],
            "prior_claims_count": 0,
            "days_since_incident": 1,
            "incident_time": "10:00",
            "interaction_count": 1,
            "proposal_rejected_before": False,
            "channel": "email",
            "description": "Daños a propiedad ajena en colisión en la calle El Conde.",
        },
    },
}


def build_initial_state(scenario_data: dict) -> dict:
    sd = scenario_data["state"]
    return {
        "claim_id": sd["claim_id"],
        "messages": [],
        "status": "open",
        "hitl_required": False,
        "decision": None,
        "extracted_data": {
            "claim_type":               sd["claim_type"],
            "client_name":              sd["client_name"],
            "conductor_name":           sd["conductor_name"],
            "amount_requested":         sd["amount_requested"],
            "submitted_docs":           sd["submitted_docs"],
            "prior_claims_count":       sd["prior_claims_count"],
            "days_since_incident":      sd["days_since_incident"],
            "incident_time":            sd["incident_time"],
            "interaction_count":        sd["interaction_count"],
            "proposal_rejected_before": sd["proposal_rejected_before"],
            "channel":                  sd["channel"],
            "description":              sd["description"],
        },
        "policy_check": None,
    }


# ── Agent runners ──────────────────────────────────────────────────────────────

async def run_agent_b(state: dict) -> dict:
    print(hdr("AGENTE B — Validación Documental", "CU-08 · R-SP-PCS-09-001/002"))
    from app.agents.agent_b import validate_claim_documents
    update = await validate_claim_documents(state)
    state["extracted_data"].update(update.get("extracted_data", {}))
    if "decision" in update:
        state["decision"] = update["decision"]
        state["status"] = update.get("status", state["status"])

    data = state["extracted_data"]
    kv("Tipo reclamación:", data["claim_type"])
    kv("Docs requeridos:", len(data.get("b_missing_docs", [])) + len(data.get("submitted_docs", [])))

    if state["decision"] == "reject":
        err(f"RECHAZO INMEDIATO: {data.get('b_reject_reason','')}")
    elif data.get("b_docs_complete"):
        ok("Documentos completos")
    else:
        missing = data.get("b_missing_docs", [])
        warn(f"Faltan {len(missing)} documento(s): {', '.join(missing)}")

    if data.get("flag_cheque_propietario"):
        warn("R-SP-PCS-09-002: conductor ≠ titular — cheque a nombre del propietario")

    return state


async def run_agent_g(state: dict) -> dict:
    print(hdr("AGENTE G — OFAC + Fraude", "CU-05 · PEPIN-POL-CP-0006"))
    from app.agents.agent_g import check_fraud_and_compliance
    update = await check_fraud_and_compliance(state)
    state["extracted_data"].update(update.get("extracted_data", {}))
    state["hitl_required"] = update.get("hitl_required", state["hitl_required"])

    data = state["extracted_data"]
    ofac = data.get("g_ofac_flagged", False)
    score = data.get("g_fraud_score", 0.0)
    dd = data.get("g_due_diligence", "simplificada")

    kv("OFAC flagged:", f"{RED}SÍ — {data.get('g_ofac_match_name','')} ({data.get('g_ofac_match_score',0):.0f}%){RESET}" if ofac else f"{GREEN}No{RESET}")
    kv("Fraud score:", f"{RED}{score:.0%}{RESET}" if score > 0.30 else f"{GREEN}{score:.0%}{RESET}")
    kv("Debida diligencia:", f"{YELLOW}{dd}{RESET}" if dd == "ampliada" else dd)
    if state["hitl_required"]:
        warn("→ HITL activado por OFAC")

    return state


async def run_agent_f(state: dict) -> dict:
    print(hdr("AGENTE F — Riesgo Judicialización (XGBoost)", "CU-10 · SP-PCS-022.3"))
    from app.agents.agent_f import predict_judicialization_risk
    update = await predict_judicialization_risk(state)
    state["extracted_data"].update(update.get("extracted_data", {}))

    data = state["extracted_data"]
    prob = data.get("f_judi_probability", 0)
    risk = data.get("f_judi_risk_level", "?")
    model = data.get("f_model_used", "?")

    risk_color = RED if risk == "HIGH" else YELLOW if risk == "MEDIUM" else GREEN
    kv("Modelo usado:", model)
    kv("Probabilidad litigio:", f"{prob:.1%}")
    kv("Nivel de riesgo:", f"{risk_color}{risk}{RESET}")

    return state


async def run_agent_c(state: dict) -> dict:
    print(hdr("AGENTE C — Extracción VLM (Claude Vision)", "CU-06"))
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        warn("Sin ANTHROPIC_API_KEY — modo PoC (descripción textual)")
        state["extracted_data"]["c_result"] = {
            "mode": "poc_text",
            "parts_damaged": ["paragolpes trasero", "faro derecho"],
            "severity": "moderate",
            "estimated_repair_RD": state["extracted_data"].get("amount_requested", 0),
        }
        kv("Partes dañadas:", state["extracted_data"]["c_result"]["parts_damaged"])
        kv("Severidad:", state["extracted_data"]["c_result"]["severity"])
        return state

    from app.agents.agent_c import extract_from_document
    update = await extract_from_document(state)
    state["extracted_data"].update(update.get("extracted_data", {}))
    result = state["extracted_data"].get("c_result", {})
    ok(f"Extracción VLM completada")
    kv("Resultado:", json.dumps(result, ensure_ascii=False)[:80] + "...")
    return state


async def run_agent_d(state: dict) -> dict:
    print(hdr("AGENTE D — Cobertura RAG (ChromaDB + Claude)", "CU-08 · R-SP-PCS-09-003/004"))
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        warn("Sin ANTHROPIC_API_KEY — usando fallback hardcoded SP-PCS-009")

    from app.agents.agent_d import check_policy_coverage
    update = await check_policy_coverage(state)
    state["policy_check"] = update.get("policy_check", {})

    pc = state["policy_check"]
    kv("Cubierto:", f"{GREEN}Sí{RESET}" if pc.get("covered") else f"{RED}No{RESET}")
    kv("Cobertura máx.:", f"RD$ {pc.get('max_coverage', 0):,.0f}")
    kv("Deducible:", f"RD$ {pc.get('deductible', 0):,.0f}")
    kv("Monto neto pagable:", f"{BOLD}RD$ {pc.get('net_payable', 0):,.0f}{RESET}")
    kv("Sección póliza:", pc.get("policy_section", ""))
    kv("Confianza:", f"{pc.get('confidence', 0):.0%}")
    if pc.get("context_chunks"):
        ok(f"RAG: {len(pc['context_chunks'])} chunks recuperados de ChromaDB")
    else:
        info("Fallback hardcoded (ChromaDB no disponible)")

    return state


async def run_agent_e(state: dict) -> dict:
    print(hdr("AGENTE E — Decisión Final (CoT + HITL)", "§3.3 SP-PCS-009"))
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        warn("Sin ANTHROPIC_API_KEY — usando reglas deterministas (_rule_based_decision)")

    from app.agents.agent_e import decide_claim
    update = await decide_claim(state)

    state["decision"] = update.get("decision")
    state["status"] = update.get("status", state["status"])
    state["hitl_required"] = update.get("hitl_required", state["hitl_required"])
    state["extracted_data"].update(update.get("extracted_data", {}))

    data = state["extracted_data"]
    pc = state.get("policy_check") or {}

    print(f"\n  {DIM}HITL triggers evaluados:{RESET}")
    print(f"    ofac_flagged:  {RED+'SÍ'+RESET if data.get('g_ofac_flagged') else GREEN+'No'+RESET}")
    print(f"    net_payable:   RD${pc.get('net_payable',0):,.0f}  {'→ '+RED+'> 500k HITL'+RESET if pc.get('net_payable',0)>500_000 else ''}")
    print(f"    fraud_score:   {data.get('g_fraud_score',0):.0%}  {'→ '+RED+'> 30% HITL'+RESET if data.get('g_fraud_score',0)>0.30 else ''}")
    print(f"    confidence:    {pc.get('confidence',0):.0%}  {'→ '+RED+'< 75% HITL'+RESET if pc.get('confidence',1)<0.75 else ''}")

    return state


def print_result(state: dict) -> None:
    decision = state.get("decision", "?")
    status   = state.get("status", "?")
    hitl     = state.get("hitl_required", False)
    rationale = state["extracted_data"].get("e_rationale", "")

    colors = {
        "approve":      GREEN,
        "reject":       RED,
        "request_info": YELLOW,
        "hitl":         PURPLE,
    }
    col = colors.get(decision, CYAN)

    print(f"""
{BOLD}{BLUE}╔══════════════════════════════════════════════════════════╗
║                   RESULTADO FINAL                        ║
╚══════════════════════════════════════════════════════════╝{RESET}

  {BOLD}Expediente:{RESET}  {state['claim_id']}
  {BOLD}Decisión:  {RESET}  {col}{BOLD}{decision.upper()}{RESET}
  {BOLD}Status:    {RESET}  {status}
  {BOLD}HITL:      {RESET}  {'Sí — revisión humana requerida' if hitl else 'No'}

  {BOLD}Razonamiento (Agent E):{RESET}
  {DIM}{rationale}{RESET}
""")

    if decision == "approve":
        pc = state.get("policy_check") or {}
        print(f"  {GREEN}{BOLD}→ Pago autorizado: RD$ {pc.get('net_payable', 0):,.0f}{RESET}\n")
    elif decision == "hitl":
        print(f"  {PURPLE}→ Expediente enviado a la Cola HITL del dashboard{RESET}\n")
    elif decision == "request_info":
        missing = state["extracted_data"].get("b_missing_docs", [])
        if missing:
            print(f"  {YELLOW}→ Documentos pendientes:{RESET}")
            for d in missing:
                print(f"      · {d}")
        print()
    elif decision == "reject":
        print(f"  {RED}→ Rechazo comunicado al reclamante{RESET}\n")


# ── Main flow ──────────────────────────────────────────────────────────────────

async def run_scenario(scenario_id: int) -> None:
    scenario = SCENARIOS[scenario_id]
    banner()
    print(f"  {BOLD}Escenario {scenario_id}:{RESET} {scenario['name']}")
    print(f"  {DIM}{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if api_key:
        ok(f"ANTHROPIC_API_KEY configurada — agentes C/D/E usarán Claude")
    else:
        warn("Sin ANTHROPIC_API_KEY — agentes C/D/E usarán fallbacks deterministas")
        info("Para usar Claude: $env:ANTHROPIC_API_KEY = 'sk-ant-api03-...'")

    state = build_initial_state(scenario)

    # ── Pipeline ───────────────────────────────────────────────────────────────
    state = await run_agent_b(state)
    if state.get("decision") == "reject":
        print_result(state)
        return

    state = await run_agent_g(state)
    if state.get("hitl_required"):
        state["decision"] = "hitl"
        state["status"] = "PENDING_REVIEW"
        print_result(state)
        return

    state = await run_agent_f(state)
    state = await run_agent_c(state)
    state = await run_agent_d(state)
    state = await run_agent_e(state)

    print_result(state)


def choose_scenario() -> int:
    print(f"\n{BOLD}  Selecciona un escenario:{RESET}\n")
    for k, v in SCENARIOS.items():
        print(f"    {BOLD}{k}{RESET}  {v['name']}")
    print()
    while True:
        try:
            choice = int(input("  Número (1-5): "))
            if 1 <= choice <= 5:
                return choice
        except (ValueError, KeyboardInterrupt):
            pass
        print("  Por favor ingresa un número del 1 al 5.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smart-Claims Agent Demo")
    parser.add_argument("--scenario", type=int, choices=[1, 2, 3, 4, 5], help="Escenario (1-5)")
    args = parser.parse_args()

    scenario_id = args.scenario if args.scenario else choose_scenario()
    asyncio.run(run_scenario(scenario_id))
