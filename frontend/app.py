"""
Smart-Claims Agent — Streamlit Dashboard
Seguros Pepín S.A. · PoC Académico (TFM)

Funciona en local Y en Streamlit Cloud:
  - Llama a los agentes directamente (sin FastAPI ni Docker)
  - ChromaDB en modo embedded (PersistentClient)
  - Pólizas ingestadas al arrancar si la colección está vacía

Configuración:
  Local:  $env:ANTHROPIC_API_KEY = "sk-ant-..."
          streamlit run frontend/app.py
  Cloud:  añadir ANTHROPIC_API_KEY en Streamlit Secrets
"""
from __future__ import annotations

import asyncio
import base64
import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO / "backend"))
os.environ.setdefault("DATA_DIR", str(_REPO / "data"))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Streamlit Cloud secrets ────────────────────────────────────────────────────
if hasattr(st, "secrets") and "ANTHROPIC_API_KEY" in st.secrets:
    os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]

HAS_KEY = bool(os.getenv("ANTHROPIC_API_KEY", ""))
BRAND_COLOR = "#003087"


# ── Async helper ───────────────────────────────────────────────────────────────
def _run(coro):
    """Run async coroutine from sync Streamlit context."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


# ── ChromaDB init (cached across reruns) ──────────────────────────────────────
@st.cache_resource(show_spinner="Iniciando base de conocimiento...")
def _init_rag() -> dict:
    """Ingest policies into embedded ChromaDB if collection is empty."""
    try:
        import chromadb  # noqa: F401 — check availability first
    except ImportError:
        return {"status": "unavailable", "docs": 0, "error": "chromadb no instalado"}
    try:
        from app.rag.retriever import get_coverage_retriever, reset_retriever_cache
        from app.rag.ingestion import ingest_policies

        reset_retriever_cache()
        retriever = _run(get_coverage_retriever())
        if retriever is None:
            return {"status": "unavailable", "docs": 0}

        count = retriever._col.count()
        if count == 0:
            ingested = _run(ingest_policies())
            reset_retriever_cache()
            return {"status": "ingested", "docs": ingested}

        return {"status": "ready", "docs": count}
    except Exception as e:
        return {"status": "error", "error": str(e), "docs": 0}


# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Smart-Claims Agent",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

rag_state = _init_rag()

# ── Role config ────────────────────────────────────────────────────────────────
ROLES = {
    "Cliente / Asegurado": {
        "icon": "👤",
        "pages": ["Reportar Reclamación", "Mis Reclamaciones", "Consulta Póliza"],
        "show_internal_scores": False,
    },
    "Agente de Servicio": {
        "icon": "🧑‍💼",
        "pages": ["Nueva Reclamación", "Cola HITL", "Gestión Pólizas", "Consulta Agente H"],
        "show_internal_scores": True,
    },
    "Supervisor / Cumplimiento": {
        "icon": "🛡️",
        "pages": ["Cola HITL", "Dashboard KPIs", "Gestión Pólizas"],
        "show_internal_scores": True,
    },
}

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image(
        "https://placehold.co/220x60/003087/white?text=Seguros+Pepín",
        use_container_width=True,
    )
    st.title("Smart-Claims Agent")
    st.caption("Sistema agéntico de gestión de reclamaciones · PoC TFM")
    st.divider()

    role = st.selectbox(
        "Accediendo como",
        list(ROLES.keys()),
        format_func=lambda r: f"{ROLES[r]['icon']} {r}",
    )
    role_cfg = ROLES[role]
    show_scores = role_cfg["show_internal_scores"]

    st.divider()

    page = st.radio(
        "Navegación",
        role_cfg["pages"],
        label_visibility="collapsed",
    )

    st.divider()

    # Status panel
    key_ok = HAS_KEY
    rag_ok = rag_state["status"] in ("ready", "ingested")

    st.caption("Estado del sistema")
    st.markdown(
        f"{'🟢' if key_ok else '🔴'} **Claude API** — {'configurada' if key_ok else 'no configurada'}"
    )
    st.markdown(
        f"{'🟢' if rag_ok else '🟡'} **ChromaDB** — "
        f"{'`' + str(rag_state['docs']) + '` chunks' if rag_ok else rag_state.get('error', 'sin pólizas')}"
    )

    if not key_ok:
        st.warning("Sin API key los agentes C/D/E usarán fallbacks.")

    st.divider()
    st.caption("Seguros Pepín S.A. · Versión académica · 2026")


# ── Helpers ────────────────────────────────────────────────────────────────────
CLAIM_TYPES = {
    "danys_propis":   "Daños Propios (§2.1)",
    "DPA":            "Daños a Propiedad Ajena (§2.2)",
    "RC":             "Responsabilidad Civil (§2.3)",
    "robatori":       "Robo Total/Parcial (§2.4)",
    "danys_mecanics": "Daños Mecánicos (§2.5 — No cubierto)",
}

REQUIRED_DOCS = {
    "danys_propis":   ["formulario_aviso_accidente", "acta_policial",
                       "licencia_conducir", "cedula", "fotos_danos", "cotizacion_taller"],
    "DPA":            ["aviso_siniestro", "acta_policial_certificada", "acta_conciliacion",
                       "presupuesto_piezas", "fotos_danos_con_placa", "matricula",
                       "cedula", "licencia_conducir"],
    "RC":             ["aviso_siniestro", "acta_policial", "cedula", "licencia_conducir", "fotos_danos"],
    "robatori":       ["denuncia_policial", "licencia_conducir", "cedula", "matricula"],
    "danys_mecanics": [],
}

DOC_LABELS = {
    "formulario_aviso_accidente": "Formulario aviso accidente (PEPIN-FRM-LR-0003)",
    "acta_policial": "Acta policial DIGESETT",
    "acta_policial_certificada": "Acta policial certificada",
    "licencia_conducir": "Licencia de conducir",
    "cedula": "Cédula de identidad",
    "fotos_danos": "Fotos del vehículo dañado",
    "cotizacion_taller": "Cotización de taller autorizado",
    "aviso_siniestro": "Aviso de siniestro",
    "acta_conciliacion": "Acta de conciliación (original)",
    "presupuesto_piezas": "Presupuesto piezas y mano de obra",
    "fotos_danos_con_placa": "Fotos con placa visible",
    "matricula": "Matrícula del vehículo",
    "denuncia_policial": "Denuncia policial (original)",
}

COVERAGE = {
    "danys_propis":   {"max": 500_000,   "deductible": 5_000},
    "DPA":            {"max": 1_000_000, "deductible": 0},
    "RC":             {"max": 2_000_000, "deductible": 0},
    "robatori":       {"max": 800_000,   "deductible": 10_000},
    "danys_mecanics": {"max": 0,         "deductible": 0},
}

STATUS_COLORS = {
    "approve":        "#28a745",
    "reject":         "#dc3545",
    "request_info":   "#ffc107",
    "hitl":           "#6f42c1",
    "RESOLVED":       "#28a745",
    "REJECTED":       "#dc3545",
    "VALIDATING":     "#ffc107",
    "PENDING_REVIEW": "#6f42c1",
}


IMAGE_DOC_TYPES = {"fotos_danos", "fotos_danos_con_placa"}
PDF_DOC_TYPES = {
    "acta_policial", "acta_policial_certificada", "acta_conciliacion",
    "denuncia_policial", "formulario_aviso_accidente", "aviso_siniestro",
    "cotizacion_taller", "presupuesto_piezas", "cedula", "licencia_conducir", "matricula",
}


def _to_data_uri(file_bytes: bytes, mime_type: str) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(file_bytes).decode()}"


def _mime(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "pdf": "application/pdf"}.get(ext, "application/octet-stream")


def _fmt_rd(n: float) -> str:
    return f"RD$ {n:,.0f}"


def _badge(text: str, color: str) -> str:
    return (
        f'<span style="background:{color};color:white;padding:3px 12px;'
        f'border-radius:12px;font-size:0.9em;font-weight:bold">{text}</span>'
    )


def _default_hitl_queue() -> list:
    return [
        {
            "claim_id": "EXP-2026-0007",
            "claim_type": "RC",
            "client": "JIMÉNEZ PAREDES HECTOR",
            "amount": 1_250_000,
            "reason": "Monto neto RD$1,250,000 supera umbral HITL de RD$500,000",
            "fraud_score": 0.05,
            "judi_risk": "MEDIUM",
            "created": "2026-05-20",
        },
        {
            "claim_id": "EXP-2026-0023",
            "claim_type": "danys_propis",
            "client": "MORALES RUIZ PABLO",
            "amount": 180_000,
            "reason": "Score fraude 38% — indicios de horario nocturno y múltiples reclamaciones",
            "fraud_score": 0.38,
            "judi_risk": "LOW",
            "created": "2026-05-21",
        },
        {
            "claim_id": "EXP-2026-0041",
            "claim_type": "DPA",
            "client": "FICTICIO GOMEZ RIOS ANTONIO RAFAEL",
            "amount": 320_000,
            "reason": "Coincidencia en lista OFAC — revisión urgente Oficial de Cumplimiento",
            "fraud_score": 0.00,
            "judi_risk": "HIGH",
            "created": "2026-05-22",
        },
    ]


def _build_state(claim_id, extracted_data):
    return {
        "claim_id": claim_id,
        "messages": [{"role": "user", "content": f"Procesar reclamación {claim_id}"}],
        "status": "VALIDATING",
        "extracted_data": extracted_data,
        "policy_check": None,
        "decision": None,
        "hitl_required": False,
    }


# ── Client-friendly decision labels ───────────────────────────────────────────
CLIENT_DECISION = {
    "approve":      ("✅ Reclamación aprobada", "#28a745",
                     "Tu reclamación ha sido aprobada. Recibirás el pago en los próximos días hábiles."),
    "reject":       ("❌ Reclamación no procedente", "#dc3545",
                     "Tu reclamación no puede ser procesada según las condiciones de tu póliza."),
    "request_info": ("📋 Documentación pendiente", "#ffc107",
                     "Necesitamos documentación adicional para continuar con tu reclamación."),
    "hitl":         ("⏳ En revisión", "#6f42c1",
                     "Tu reclamación está siendo revisada por nuestro equipo especializado. Te contactaremos pronto."),
}

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — Nueva Reclamación / Reportar Reclamación
# ══════════════════════════════════════════════════════════════════════════════
if page in ("Nueva Reclamación", "Reportar Reclamación"):
    if page == "Reportar Reclamación":
        st.title("Reportar un Accidente")
        st.caption("Rellena el formulario con los detalles del incidente. Nuestro sistema lo procesará de forma inmediata.")
    else:
        st.title("Nueva Reclamación")
        st.caption("El formulario invoca los 8 agentes en tiempo real — sin mock")

    with st.form("claim_form"):
        col1, col2 = st.columns(2)

        with col1:
            claim_type = st.selectbox(
                "Tipo de reclamación",
                options=list(CLAIM_TYPES.keys()),
                format_func=lambda k: CLAIM_TYPES[k],
            )
            client_name = st.text_input(
                "Nombre del asegurado (apellidos primero)",
                placeholder="RODRIGUEZ PEREZ JUAN",
            )
            conductor_name = st.text_input(
                "Conductor (si difiere del asegurado)",
                placeholder="Dejar vacío si es el mismo",
            )
            policy_number = st.text_input("Número de póliza", placeholder="SP-PCS-009-12345")
            prior_claims = st.number_input("Reclamaciones previas", min_value=0, max_value=20, value=0)
            prior_coverage_used = st.number_input(
                "Cobertura ya consumida en este período (RD$)",
                min_value=0.0, max_value=5_000_000.0, step=10_000.0, value=0.0,
            )

        with col2:
            amount = st.number_input(
                "Monto solicitado (RD$)",
                min_value=0.0, max_value=5_000_000.0, step=1_000.0,
            )
            incident_date = st.date_input(
                "Fecha del incidente", value=date.today() - timedelta(days=3)
            )
            incident_time = st.text_input("Hora del incidente (HH:MM)", value="14:30")
            days_since = (date.today() - incident_date).days
            channel = st.selectbox("Canal de entrada", ["email", "phone", "presencial"])
            incident_desc = st.text_area(
                "Descripción del incidente",
                placeholder="Colisión trasera en semáforo. Paragolpes y faro dañados...",
                height=100,
            )

        st.divider()
        st.subheader("Documentos adjuntos")
        if page == "Reportar Reclamación":
            st.caption(
                "Todos los documentos marcados con ⚠️ son **obligatorios**. "
                "Las fotos deben subirse en formato digital. "
                "Los documentos físicos pueden confirmarse si ya fueron entregados en oficina."
            )
        else:
            st.caption(
                "⚠️ = obligatorio. Fotos → upload digital (analizadas por Vision IA). "
                "Documentos físicos → upload digital o confirmar entrega presencial."
            )

        required = REQUIRED_DOCS.get(claim_type, [])
        uploaded_files: dict[str, object] = {}   # doc_key → file object
        physical_confirmed: dict[str, bool] = {}  # doc_key → confirmed in-person

        if required:
            doc_cols = st.columns(2)
            for i, doc_key in enumerate(required):
                with doc_cols[i % 2]:
                    label = DOC_LABELS.get(doc_key, doc_key)
                    if doc_key in IMAGE_DOC_TYPES:
                        # Photos: digital upload mandatory
                        f = st.file_uploader(
                            f"⚠️ 📷 {label}",
                            type=["jpg", "jpeg", "png"],
                            key=f"doc_{i}",
                            help="Obligatorio — JPG o PNG, analizado por Claude Vision",
                        )
                        if f is not None:
                            uploaded_files[doc_key] = f
                    else:
                        # Physical docs: upload OR in-person confirmation
                        f = st.file_uploader(
                            f"⚠️ 📄 {label}",
                            type=["pdf", "jpg", "jpeg", "png"],
                            key=f"doc_{i}",
                            help="Obligatorio — sube el archivo o confirma entrega presencial abajo",
                        )
                        confirmed = st.checkbox(
                            "Presentado físicamente en oficina",
                            key=f"phys_{i}",
                        )
                        if f is not None:
                            uploaded_files[doc_key] = f
                        if confirmed:
                            physical_confirmed[doc_key] = True
        else:
            st.error("Daños mecánicos (§2.5) — No cubiertos. Será rechazado automáticamente.")

        if required and show_scores:
            with st.expander("Límites de cobertura SP-PCS-009"):
                cov = COVERAGE[claim_type]
                c1, c2 = st.columns(2)
                c1.metric("Límite máximo", _fmt_rd(cov["max"]) if cov["max"] else "No cubierto")
                c2.metric("Deducible", _fmt_rd(cov["deductible"]) if cov["max"] else "—")

        submitted = st.form_submit_button("Procesar reclamación", type="primary")

    # ── Procesamiento con agentes reales ──────────────────────────────────────
    if submitted:
        # ── Validación de campos mínimos (hard stop) ──────────────────────────
        hard_errors = []
        if not client_name.strip():
            hard_errors.append("El nombre del asegurado es obligatorio.")
        if not policy_number.strip():
            hard_errors.append("El número de póliza es obligatorio.")
        if amount <= 0:
            hard_errors.append("El monto solicitado debe ser mayor a RD$0.")
        if hard_errors:
            for err in hard_errors:
                st.error(err)
            st.stop()

        claim_id = f"EXP-2026-{uuid.uuid4().hex[:4].upper()}"
        conductor = conductor_name.strip() or client_name.strip()

        # Build submitted_docs list from uploaded files + physical confirmations
        submitted_docs = list(set(list(uploaded_files.keys()) + list(physical_confirmed.keys())))

        # ── Toll gate: documentos obligatorios ───────────────────────────────
        missing_mandatory = []
        if required:
            for doc_key in required:
                provided = (
                    doc_key in uploaded_files
                    or physical_confirmed.get(doc_key, False)
                )
                if not provided:
                    missing_mandatory.append(doc_key)

        if missing_mandatory:
            # Save as PENDING_DOCS — don't run agents yet
            if "submitted_claims" not in st.session_state:
                st.session_state.submitted_claims = []
            st.session_state.submitted_claims.append({
                "claim_id": claim_id,
                "claim_type": claim_type,
                "decision": "pending_docs",
                "amount": float(amount),
                "client": client_name.strip().upper(),
                "policy_number": policy_number.strip(),
                "description": incident_desc,
                "missing_docs": missing_mandatory,
                "uploaded_files_keys": list(uploaded_files.keys()),
                "physical_confirmed_keys": list(physical_confirmed.keys()),
                "fraud_score": 0,
                "judi_risk": "—",
                "net_payable": 0,
                "date": date.today().isoformat(),
            })

            st.warning(f"Expediente **{claim_id}** registrado en estado **PENDIENTE DE DOCUMENTACIÓN**.")
            st.error("Faltan los siguientes documentos obligatorios:")
            for dk in missing_mandatory:
                st.markdown(f"  • {DOC_LABELS.get(dk, dk)}")
            st.info(
                "Puedes aportar los documentos faltantes desde **Mis Reclamaciones** "
                "cuando los tengas disponibles. El expediente será procesado automáticamente "
                "una vez estén completos."
            )
            st.stop()

        # Find primary image for Agent C (first image-type doc uploaded)
        primary_image_uri = ""
        primary_doc_type = "fotos_danos"
        for doc_key, f in uploaded_files.items():
            if doc_key in IMAGE_DOC_TYPES:
                img_bytes = f.read()
                primary_image_uri = _to_data_uri(img_bytes, _mime(f.name))
                primary_doc_type = doc_key
                break
        # Fallback: use first non-image upload as text input
        if not primary_image_uri and uploaded_files:
            primary_doc_type = next(iter(uploaded_files))

        extracted = {
            "claim_type": claim_type,
            "client_name": client_name.strip().upper(),
            "conductor_name": conductor.upper(),
            "amount_requested": float(amount),
            "submitted_docs": submitted_docs,
            "prior_claims_count": int(prior_claims),
            "prior_coverage_used": float(prior_coverage_used),
            "days_since_incident": int(days_since),
            "interaction_count": 1,
            "proposal_rejected_before": False,
            "incident_time": incident_time,
            "channel": channel,
            "description": incident_desc,
            "doc_type": primary_doc_type,
            "file_url": primary_image_uri,
            "uploaded_doc_types": list(uploaded_files.keys()),
            "b_docs_complete": True,
            "b_missing_docs": [],
            "g_fraud_score": 0.0,
            "g_ofac_flagged": False,
        }

        state = _build_state(claim_id, extracted)

        st.divider()

        # ── Pre-validación de documentos con Agent C ──────────────────────────
        from app.agents.agent_c import validate_document as _validate_doc

        image_uploads = {k: v for k, v in uploaded_files.items() if k in IMAGE_DOC_TYPES}
        all_uploads = uploaded_files  # includes non-image docs too

        doc_validation_passed = True
        invalid_docs = []

        if all_uploads:
            val_header = "🔎 Validando documentos adjuntos..." if not show_scores else None
            with st.expander(
                "🔎 Validación de documentos (Agent C — pre-pipeline)",
                expanded=True,
            ) if show_scores else st.spinner("Verificando que los documentos sean válidos..."):

                val_results = {}
                for dk, f in all_uploads.items():
                    f.seek(0)
                    img_bytes = f.read()
                    data_uri = _to_data_uri(img_bytes, _mime(f.name))
                    result = _run(_validate_doc(dk, data_uri, claim_id))
                    val_results[dk] = result

                    if show_scores:
                        icon = "✅" if result["valid"] else ("⚠️" if result.get("skipped") else "❌")
                        label = DOC_LABELS.get(dk, dk)
                        note = result.get("reason", "")
                        if result.get("skipped"):
                            st.caption(f"{icon} **{label}** — {note}")
                        elif result["valid"]:
                            st.success(f"{icon} **{label}** — {note}")
                        else:
                            st.error(f"{icon} **{label}** — {note}")

                    if not result["valid"] and not result.get("skipped"):
                        doc_validation_passed = False
                        invalid_docs.append((dk, result.get("reason", "")))

        if invalid_docs:
            st.error("Los siguientes documentos no superaron la validación:")
            for dk, reason in invalid_docs:
                st.markdown(f"  • **{DOC_LABELS.get(dk, dk)}**: {reason}")
            st.warning("Por favor sube documentos válidos y vuelve a intentarlo.")
            st.stop()

        if show_scores:
            st.subheader(f"Procesando expediente `{claim_id}`")
        else:
            st.info("Documentos validados. Procesando tu reclamación...")

        try:
            from app.agents.agent_b import validate_claim_documents
            from app.agents.agent_g import check_fraud_and_compliance
            from app.agents.agent_f import predict_judicialization_risk
            from app.agents.agent_c import extract_from_document
            from app.agents.agent_d import check_policy_coverage
            from app.agents.agent_e import decide_claim

            # ── Agent B ──────────────────────────────────────────────────────
            label_b = "🔍 Agente B — Validación Documental" if show_scores else "📋 Verificando documentación"
            with st.expander(label_b, expanded=True):
                with st.spinner("Verificando documentos..."):
                    res_b = _run(validate_claim_documents(state))
                state["extracted_data"].update(res_b.get("extracted_data", {}))
                if res_b.get("decision") == "reject":
                    reason = state["extracted_data"].get("b_reject_reason", "")
                    if show_scores:
                        st.error(f"❌ Rechazo inmediato: {reason}")
                        st.markdown(_badge("REJECT", STATUS_COLORS["reject"]), unsafe_allow_html=True)
                    else:
                        st.error("Tu reclamación no puede procesarse con la documentación aportada.")
                        if reason:
                            st.caption(reason)
                    st.stop()
                missing = state["extracted_data"].get("b_missing_docs", [])
                if missing:
                    if show_scores:
                        st.warning(f"Documentos faltantes: {', '.join(missing)}")
                    else:
                        st.warning(f"Faltan documentos: {', '.join([DOC_LABELS.get(d, d) for d in missing])}")
                else:
                    st.success("✅ Documentación correcta")
                if show_scores and state["extracted_data"].get("flag_cheque_propietario"):
                    st.info("ℹ️ R-SP-PCS-09-002: Conductor ≠ propietario — cheque a nombre del propietario")

            # ── Agent G ──────────────────────────────────────────────────────
            with st.spinner("Verificando identidad...") if not show_scores else st.expander("🛡️ Agente G — OFAC + Fraude", expanded=True):
                res_g = _run(check_fraud_and_compliance(state))
                state["extracted_data"].update(res_g.get("extracted_data", {}))
                state["hitl_required"] = res_g.get("hitl_required", False)
                if show_scores:
                    g = state["extracted_data"]
                    c1, c2, c3 = st.columns(3)
                    ofac_ok = not g.get("g_ofac_flagged", False)
                    c1.metric("OFAC", "LIMPIO" if ofac_ok else f"⚠️ {g.get('g_ofac_match_name', '')}")
                    c2.metric("Score fraude", f"{g.get('g_fraud_score', 0):.0%}")
                    c3.metric("Debida diligencia", g.get("g_due_diligence", "simplificada").upper())
                    if g.get("g_ofac_flagged"):
                        st.error(f"⚠️ OFAC: {g.get('g_ofac_match_name')} — score {g.get('g_ofac_match_score', 0):.0f}%")

            # ── Agent F ──────────────────────────────────────────────────────
            with st.spinner("Analizando caso...") if not show_scores else st.expander("⚖️ Agente F — Riesgo Judicialización (XGBoost)", expanded=True):
                res_f = _run(predict_judicialization_risk(state))
                state["extracted_data"].update(res_f.get("extracted_data", {}))
                if show_scores:
                    f = state["extracted_data"]
                    risk = f.get("f_judi_risk_level", "LOW")
                    c1, c2 = st.columns(2)
                    c1.metric("Probabilidad litigio", f"{f.get('f_judi_probability', 0):.1%}")
                    c2.metric("Nivel de riesgo", risk)
                    st.caption(f"Modelo: {f.get('f_model_used', '—')}")

            # ── Agent C ──────────────────────────────────────────────────────
            with st.spinner("Procesando documentos...") if not show_scores else st.expander("📸 Agente C — Extracción VLM (Claude Vision)", expanded=True):
                if show_scores and not HAS_KEY:
                    st.warning("Sin API key — modo PoC (descripción textual)")
                res_c = _run(extract_from_document(state))
                state["extracted_data"].update(res_c.get("extracted_data", {}))
                if show_scores:
                    c_res = state["extracted_data"].get("c_result", {})
                    if "error" not in c_res:
                        st.json(c_res)
                    else:
                        st.caption(f"Resultado: {c_res}")

            # ── Agent D ──────────────────────────────────────────────────────
            with st.spinner("Consultando condiciones de póliza...") if not show_scores else st.expander("📋 Agente D — Cobertura RAG (ChromaDB + Claude)", expanded=True):
                if show_scores and not HAS_KEY:
                    st.warning("Sin API key — fallback a reglas SP-PCS-009 hardcoded")
                res_d = _run(check_policy_coverage(state))
                state["policy_check"] = res_d.get("policy_check", {})
                if show_scores:
                    pc = state["policy_check"]
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Cubierto", "Sí" if pc.get("covered") else "No")
                    c2.metric("Cobertura máx.", _fmt_rd(pc.get("max_coverage", 0)))
                    c3.metric("Deducible", _fmt_rd(pc.get("deductible", 0)))
                    c4.metric("Neto pagable", _fmt_rd(pc.get("net_payable", 0)))
                    st.caption(f"Sección: {pc.get('policy_section', '—')}  ·  Confianza: {pc.get('confidence', 0):.0%}")
                    chunks = pc.get("context_chunks", [])
                    if chunks:
                        with st.expander(f"📄 Chunks RAG recuperados ({len(chunks)})", expanded=False):
                            for ch in chunks:
                                st.markdown(f"**{ch['source']}** (dist: {ch['distance']})")
                                st.text(ch["document"][:300] + "..." if len(ch["document"]) > 300 else ch["document"])
                                st.divider()

            # ── Agent E ──────────────────────────────────────────────────────
            with st.spinner("Tomando decisión final...") if not show_scores else st.expander("🧠 Agente E — Decisión Final (CoT + HITL)", expanded=True):
                if show_scores and not HAS_KEY:
                    st.warning("Sin API key — usando _rule_based_decision() determinista")
                res_e = _run(decide_claim(state))
                state.update(res_e)
                state["extracted_data"].update(res_e.get("extracted_data", {}))
                if show_scores:
                    decision = state.get("decision", "request_info")
                    color = STATUS_COLORS.get(decision, "#6c757d")
                    st.markdown(f"**Decisión:** " + _badge(decision.upper(), color), unsafe_allow_html=True)
                    rationale = state["extracted_data"].get("e_rationale", "")
                    if rationale:
                        st.info(f"💬 {rationale}")

            # ── Resultado final ───────────────────────────────────────────────
            st.divider()
            decision = state.get("decision", "request_info")

            if show_scores:
                color = STATUS_COLORS.get(decision, "#6c757d")
                st.markdown(f"## Resultado: " + _badge(decision.upper(), color), unsafe_allow_html=True)
                rc1, rc2, rc3 = st.columns(3)
                rc1.metric("Expediente", claim_id)
                rc2.metric("Estado", state.get("status", "VALIDATING"))
                if decision == "approve":
                    rc3.metric("Pago autorizado", _fmt_rd(state["policy_check"].get("net_payable", 0)))
                elif decision == "hitl":
                    rc3.metric("Cola HITL", "Enviado a revisión humana")
                elif decision == "request_info":
                    missing = state["extracted_data"].get("b_missing_docs", [])
                    rc3.metric("Documentos pendientes", str(len(missing)))
            else:
                label, color, msg = CLIENT_DECISION.get(decision, CLIENT_DECISION["request_info"])
                st.markdown(
                    f'<div style="background:{color};color:white;padding:20px;border-radius:10px;text-align:center">'
                    f'<h2 style="margin:0">{label}</h2>'
                    f'<p style="margin:8px 0 0">{msg}</p>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                st.caption(f"Número de expediente: **{claim_id}** — Guárdalo para hacer seguimiento.")

            # ── Persist to session state ──────────────────────────────────────
            if "submitted_claims" not in st.session_state:
                st.session_state.submitted_claims = []
            st.session_state.submitted_claims.append({
                "claim_id": claim_id,
                "claim_type": claim_type,
                "decision": decision,
                "amount": float(amount),
                "client": client_name.strip().upper(),
                "fraud_score": state["extracted_data"].get("g_fraud_score", 0),
                "judi_risk": state["extracted_data"].get("f_judi_risk_level", "LOW"),
                "net_payable": (state.get("policy_check") or {}).get("net_payable", 0),
                "date": date.today().isoformat(),
            })
            # Push HITL cases to the shared queue
            if decision == "hitl":
                if "hitl_queue" not in st.session_state:
                    st.session_state.hitl_queue = _default_hitl_queue()
                st.session_state.hitl_queue.append({
                    "claim_id": claim_id,
                    "claim_type": claim_type,
                    "client": client_name.strip().upper(),
                    "amount": float(amount),
                    "reason": state["extracted_data"].get("e_rationale", "Revisión requerida"),
                    "fraud_score": state["extracted_data"].get("g_fraud_score", 0),
                    "judi_risk": state["extracted_data"].get("f_judi_risk_level", "LOW"),
                    "created": date.today().isoformat(),
                })
                if decision == "approve":
                    pc = state.get("policy_check") or {}
                    if pc.get("net_payable"):
                        st.success(f"Monto aprobado: **{_fmt_rd(pc['net_payable'])}**")
                elif decision == "request_info":
                    missing = state["extracted_data"].get("b_missing_docs", [])
                    if missing:
                        st.warning("Documentos requeridos:\n" + "\n".join(f"- {DOC_LABELS.get(d, d)}" for d in missing))

        except Exception as exc:
            st.error(f"Error en el pipeline: {exc}")
            import traceback
            st.code(traceback.format_exc())


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — Gestión Pólizas
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Gestión Pólizas":
    st.title("Gestión de Pólizas — Base de Conocimiento RAG")
    st.caption("Sube documentos de póliza para que el Agente D los consulte al evaluar reclamaciones")

    # Status actual
    col_s1, col_s2 = st.columns(2)
    col_s1.metric(
        "Estado ChromaDB",
        rag_state["status"].upper(),
        delta="embedded" if rag_state["status"] != "unavailable" else None,
    )
    col_s2.metric("Chunks indexados", rag_state.get("docs", 0))

    st.divider()

    # Documentos ya indexados
    st.subheader("Documentos en la base de conocimiento")
    policies_dir = Path(os.environ["DATA_DIR"]) / "policies"
    files_in_dir = list(policies_dir.glob("*.md")) if policies_dir.exists() else []

    if files_in_dir:
        for f in files_in_dir:
            size_kb = f.stat().st_size // 1024
            st.markdown(f"📄 **{f.name}** — {size_kb} KB")
    else:
        st.info("No hay documentos en data/policies/")

    st.divider()

    # Uploader de nuevas pólizas
    st.subheader("Subir nueva póliza")
    st.caption(
        "Sube un fichero .md con el contenido de la póliza. "
        "Se fragmentará en chunks de 600 caracteres y se indexará en ChromaDB."
    )

    uploaded = st.file_uploader(
        "Selecciona un fichero de póliza (.md o .txt)",
        type=["md", "txt"],
        help="El documento debe estar en español y describir coberturas, exclusiones, deducibles y límites.",
    )

    if uploaded is not None:
        content = uploaded.read().decode("utf-8")
        st.text_area("Vista previa (primeros 500 chars)", content[:500] + "...", height=150)

        col_u1, col_u2 = st.columns([1, 3])
        if col_u1.button("Ingestar en ChromaDB", type="primary"):
            save_path = policies_dir / uploaded.name
            policies_dir.mkdir(parents=True, exist_ok=True)
            save_path.write_text(content, encoding="utf-8")

            with st.spinner(f"Ingestionando {uploaded.name}..."):
                try:
                    from app.rag.ingestion import ingest_policies
                    from app.rag.retriever import reset_retriever_cache
                    total = _run(ingest_policies(policies_dir))
                    reset_retriever_cache()
                    st.cache_resource.clear()
                    st.success(f"✅ {total} chunks indexados. ChromaDB actualizado.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error durante la ingestión: {e}")

    st.divider()

    # Test RAG query
    st.subheader("Probar consulta RAG")
    test_query = st.text_input(
        "Pregunta de prueba",
        placeholder="¿Cuál es el deducible para daños propios?",
    )
    if st.button("Consultar") and test_query:
        with st.spinner("Buscando en ChromaDB..."):
            try:
                from app.rag.retriever import get_coverage_retriever, reset_retriever_cache
                reset_retriever_cache()
                retriever = _run(get_coverage_retriever())
                if retriever and retriever._col.count() > 0:
                    results = retriever.query(test_query, n_results=3)
                    if results:
                        for i, r in enumerate(results, 1):
                            with st.expander(f"Resultado {i} — {r['source']} (distancia: {r['distance']})", expanded=i == 1):
                                st.write(r["document"])
                    else:
                        st.warning("Sin resultados. Verifica que hay documentos indexados.")
                else:
                    st.warning("ChromaDB sin documentos. Sube una póliza primero.")
            except Exception as e:
                st.error(f"Error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — Cola HITL
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Cola HITL":
    st.title("Cola Human-in-the-Loop (HITL)")
    st.caption("Expedientes pendientes de revisión humana — SP-PCS-009 §3.3")

    if "hitl_queue" not in st.session_state:
        st.session_state.hitl_queue = _default_hitl_queue()

    queue = [e for e in st.session_state.hitl_queue if e.get("status") is None]
    st.metric("Expedientes en cola", len(queue))

    if not queue:
        st.success("✅ Cola HITL vacía — todos los expedientes han sido revisados.")

    for item in queue:
        with st.container(border=True):
            h1, h2 = st.columns([3, 1])
            with h1:
                st.subheader(f"{item['claim_id']} — {CLAIM_TYPES.get(item['claim_type'], item['claim_type'])}")
                st.markdown(f"**Cliente:** {item['client']}")
                st.markdown(f"**Motivo HITL:** {item['reason']}")
                st.caption(f"Creado: {item['created']}")
            with h2:
                st.metric("Monto", _fmt_rd(item["amount"]))
                fraud_color = "#dc3545" if item["fraud_score"] > 0.30 else "#28a745"
                st.markdown(
                    f"**Fraude:** <span style='color:{fraud_color}'>{item['fraud_score']:.0%}</span>",
                    unsafe_allow_html=True,
                )
                jc = {"HIGH": "#dc3545", "MEDIUM": "#ffc107", "LOW": "#28a745"}.get(item["judi_risk"], "#6c757d")
                st.markdown(
                    f"**Litigio:** <span style='color:{jc}'>{item['judi_risk']}</span>",
                    unsafe_allow_html=True,
                )

            ca, cr, ci = st.columns(3)
            if ca.button("✅ Aprobar", key=f"a_{item['claim_id']}", type="primary"):
                item["status"] = "approved"
                st.success(f"{item['claim_id']} aprobado. Notificando a Tesorería...")
                st.rerun()
            if cr.button("❌ Rechazar", key=f"r_{item['claim_id']}"):
                item["status"] = "rejected"
                st.error(f"{item['claim_id']} rechazado.")
                st.rerun()
            if ci.button("📋 Pedir info", key=f"i_{item['claim_id']}"):
                item["status"] = "info_requested"
                st.warning(f"{item['claim_id']}: documentación adicional solicitada.")
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — Dashboard KPIs
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Dashboard KPIs":
    st.title("Dashboard KPIs")
    st.caption("Métricas de rendimiento del sistema Smart-Claims · Enero–Mayo 2026")

    # Session stats (real)
    session_claims = st.session_state.get("submitted_claims", [])
    session_total = len(session_claims)
    session_hitl = len([c for c in session_claims if c["decision"] == "hitl"])
    session_approved = len([c for c in session_claims if c["decision"] == "approve"])
    session_auto = (session_approved + len([c for c in session_claims if c["decision"] == "reject"])) / max(session_total, 1)

    if session_total:
        st.subheader("Esta sesión")
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Reclamaciones procesadas", session_total)
        s2.metric("Aprobadas", session_approved)
        s3.metric("En cola HITL", session_hitl)
        s4.metric("Tasa automatización", f"{session_auto:.0%}")
        if session_claims:
            df_s = pd.DataFrame(session_claims)
            dec_counts = df_s["decision"].value_counts().reset_index()
            dec_counts.columns = ["Decisión", "Cantidad"]
            fig_s = px.bar(dec_counts, x="Decisión", y="Cantidad", color="Decisión",
                           color_discrete_map={"approve": "#28a745", "reject": "#dc3545",
                                               "hitl": "#6f42c1", "request_info": "#ffc107"},
                           title="Decisiones en esta sesión")
            fig_s.update_layout(height=250, showlegend=False, margin=dict(t=40, b=20))
            st.plotly_chart(fig_s, use_container_width=True)
        st.divider()

    st.subheader("Histórico enero–mayo 2026")
    dates = [date(2026, 1, 1) + timedelta(weeks=i) for i in range(21)]
    weekly = [28, 31, 25, 33, 29, 35, 38, 30, 27, 32, 40, 36, 34, 29, 37, 41, 38, 33, 35, 39, 42]
    auto_pct = [68, 70, 71, 69, 72, 74, 73, 75, 76, 74, 77, 78, 76, 79, 78, 80, 81, 79, 82, 81, 83]
    avg_days = [18, 17, 19, 16, 15, 14, 16, 13, 15, 14, 12, 13, 11, 12, 10, 11, 10, 9, 10, 9, 8]

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total expedientes", f"{712 + session_total}")
    k2.metric("Automatización", "79%", delta="+15% vs. AS-IS")
    k3.metric("Días promedio", "10.2", delta="-8 días vs. AS-IS", delta_color="inverse")
    k4.metric("Cola HITL activa", f"{47 + session_hitl}")
    k5.metric("Judicializados", "71 (10%)")

    st.divider()
    df_dates = pd.to_datetime([d.isoformat() for d in dates])

    cl, cr = st.columns(2)
    with cl:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_dates, y=auto_pct, mode="lines+markers",
            line=dict(color=BRAND_COLOR, width=2),
            fill="tozeroy", fillcolor="rgba(0,48,135,0.1)",
        ))
        fig.add_hline(y=80, line_dash="dash", line_color="green", annotation_text="Objetivo 80%")
        fig.update_layout(title="Tasa de automatización semanal", yaxis_title="%", height=300, margin=dict(t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

    with cr:
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(x=df_dates, y=avg_days, marker_color=BRAND_COLOR))
        fig2.add_hline(y=18, line_dash="dash", line_color="red", annotation_text="AS-IS: 18 días")
        fig2.update_layout(title="Días promedio de resolución", yaxis_title="Días", height=300, margin=dict(t=40, b=20))
        st.plotly_chart(fig2, use_container_width=True)

    cl2, cr2 = st.columns(2)
    with cl2:
        fig3 = px.pie(
            values=[514, 47, 47, 71, 33],
            names=["Aprobados auto", "Rechazados auto", "HITL pendiente", "Judicializados", "Info solicitada"],
            color_discrete_sequence=["#28a745", "#dc3545", "#6f42c1", "#ffc107", "#17a2b8"],
            title="Distribución de decisiones", hole=0.4,
        )
        fig3.update_layout(height=300, margin=dict(t=40, b=20))
        st.plotly_chart(fig3, use_container_width=True)

    with cr2:
        fig4 = px.bar(
            x=["Daños Propios", "DPA", "RC", "Robo"],
            y=[3.2, 8.5, 12.1, 4.7],
            title="% Judicialización por tipo (Agente F)",
            color_discrete_sequence=[BRAND_COLOR],
        )
        fig4.add_hline(y=10, line_dash="dash", line_color="red", annotation_text="Histórico 10%")
        fig4.update_layout(height=300, margin=dict(t=40, b=20), showlegend=False)
        st.plotly_chart(fig4, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE — Mis Reclamaciones (Cliente)
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Mis Reclamaciones":
    st.title("Mis Reclamaciones")
    st.caption("Consulta el estado de tus reclamaciones activas")

    CLIENT_DECISION["pending_docs"] = (
        "📋 Documentación pendiente", "#fd7e14",
        "Tu expediente está registrado pero necesitamos documentación adicional para procesarlo."
    )

    if "submitted_claims" not in st.session_state or not st.session_state.get("submitted_claims"):
        st.info("No tienes reclamaciones registradas en esta sesión. Usa **Reportar Reclamación** para iniciar una.")
    else:
        for idx, cl in enumerate(st.session_state.submitted_claims):
            with st.container(border=True):
                c1, c2, c3 = st.columns(3)
                c1.metric("Expediente", cl["claim_id"])
                c2.metric("Tipo", CLAIM_TYPES.get(cl["claim_type"], cl["claim_type"]))
                label, color, msg = CLIENT_DECISION.get(cl["decision"], CLIENT_DECISION["request_info"])
                c3.markdown(
                    f'<span style="background:{color};color:white;padding:4px 12px;border-radius:8px">{label}</span>',
                    unsafe_allow_html=True,
                )
                st.caption(msg)

                # Pending docs: show what's missing + uploader to complete
                if cl["decision"] == "pending_docs" and cl.get("missing_docs"):
                    with st.expander("Completar documentación faltante"):
                        st.warning("Documentos requeridos para procesar tu expediente:")
                        completed_uploads = {}
                        phys_confirmed = {}
                        for dk in cl["missing_docs"]:
                            doc_label = DOC_LABELS.get(dk, dk)
                            if dk in IMAGE_DOC_TYPES:
                                uf = st.file_uploader(
                                    f"📷 {doc_label}",
                                    type=["jpg", "jpeg", "png"],
                                    key=f"complete_{idx}_{dk}",
                                )
                                if uf:
                                    completed_uploads[dk] = uf
                            else:
                                uf = st.file_uploader(
                                    f"📄 {doc_label}",
                                    type=["pdf", "jpg", "jpeg", "png"],
                                    key=f"complete_{idx}_{dk}",
                                )
                                confirmed = st.checkbox(
                                    "Presentado físicamente",
                                    key=f"complete_phys_{idx}_{dk}",
                                )
                                if uf:
                                    completed_uploads[dk] = uf
                                if confirmed:
                                    phys_confirmed[dk] = True

                        still_missing = [
                            dk for dk in cl["missing_docs"]
                            if dk not in completed_uploads and not phys_confirmed.get(dk)
                        ]
                        if not still_missing:
                            st.success("✅ Todos los documentos están completos. Listo para procesar.")
                            if st.button("Enviar y procesar reclamación", key=f"process_{idx}", type="primary"):
                                st.info("Procesando... Ve a **Reportar Reclamación** con todos los documentos para ejecutar el pipeline completo.")
                        else:
                            st.caption(f"Faltan {len(still_missing)} documento(s) más.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE — Consulta Póliza (Cliente) / Consulta Agente H (Agente)
# ══════════════════════════════════════════════════════════════════════════════
elif page in ("Consulta Agente H", "Consulta Póliza"):
    if page == "Consulta Póliza":
        st.title("Consulta sobre tu Póliza")
        st.caption("Pregunta sobre coberturas, documentos requeridos, límites y plazos.")
    else:
        st.title("Consulta Agente H — Asistente Experto")
        st.caption(
            "RAG conversacional sobre SP-PCS-009, SP-PCS-022 y PEPIN-POL-CP-0006. "
            "Las respuestas citan la sección exacta de la póliza."
        )

    if not HAS_KEY:
        st.warning("⚠️ Sin ANTHROPIC_API_KEY el Agente H no puede responder. Configura la clave en los secrets.")

    if "h_messages" not in st.session_state:
        st.session_state.h_messages = [
            {
                "role": "assistant",
                "content": (
                    "Hola. Soy el Asistente Experto Smart-Claims. Puedo responder sobre coberturas, "
                    "documentos requeridos, plazos, debida diligencia y judicialización. ¿En qué te ayudo?"
                ),
            }
        ]

    for msg in st.session_state.h_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    suggested = [
        "¿Qué documentos necesito para una reclamación DPA?",
        "¿Cuál es el deducible para daños propios?",
        "¿Cuándo se activa la debida diligencia ampliada?",
        "¿Qué factores aumentan el riesgo de judicialización?",
    ]
    st.caption("Preguntas frecuentes:")
    sug_cols = st.columns(len(suggested))
    triggered = None
    for i, (col, q) in enumerate(zip(sug_cols, suggested)):
        if col.button(q[:28] + "…", key=f"sug_{i}", help=q):
            triggered = q

    user_input = st.chat_input("Escribe tu consulta sobre la póliza o el expediente...")
    query = triggered or user_input

    if query:
        st.session_state.h_messages.append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)

        with st.chat_message("assistant"):
            with st.spinner("Consultando póliza..."):
                try:
                    from app.agents.agent_h import answer_expert_query
                    state_h = _build_state("QUERY-H", {"h_query": query})
                    res_h = _run(answer_expert_query(state_h))
                    answer = res_h["extracted_data"].get("h_result", "Sin respuesta.")
                    sources = res_h["extracted_data"].get("h_sources", [])
                except Exception as exc:
                    answer = f"Error al consultar el agente: {exc}"
                    sources = []

            st.markdown(answer)
            if sources:
                st.caption(f"📄 Fuentes: {', '.join(sources)}")

        st.session_state.h_messages.append({"role": "assistant", "content": answer})
