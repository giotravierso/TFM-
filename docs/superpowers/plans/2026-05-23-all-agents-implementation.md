# Smart-Claims Agent — Implementation Plan (All Agents)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement agents B–H of the Smart-Claims agentic system for Seguros Pepín, S.A., covering document validation, multimodal extraction, coverage RAG, decision+HITL, judicialization prediction, fraud/AML, and RAG assistant.

**Architecture:** LangGraph orchestrator (Agent A, already implemented) dispatches to 7 specialist agents (B–H). Each agent is a pure async function that receives `ClaimState` and returns a partial state update. Agents D and H share a ChromaDB collection (`smart_claims_policies`).

**Tech Stack:** Python 3.11 · FastAPI · LangGraph · Claude claude-sonnet-4-20250514 / Claude Vision · ChromaDB · XGBoost · rapidfuzz · Faker · ReportLab

---

## File Map

| File | Responsibility | Owner |
|------|---------------|-------|
| `data/policies/poliza_sp_pcs_009.md` | Synthetic policy doc (ChromaDB source) | Foundation |
| `data/ofac_mock.json` | 30 fictitious sanctioned names | Foundation |
| `data/synthetic/generator.py` | Generate 100-case dataset with ground truth | Foundation |
| `data/synthetic/train_agent_f.py` | Train XGBoost judicialization model | Agent F |
| `data/models/agent_f_xgboost.pkl` | Trained model artifact | Agent F |
| `backend/app/rag/ingestion.py` | Load policy docs → ChromaDB | Foundation |
| `backend/app/rag/retriever.py` | Query ChromaDB for Agents D & H | Foundation |
| `backend/app/agents/agent_b.py` | Document validation + rule engine | Agent B |
| `backend/app/agents/agent_c.py` | VLM extraction (Claude Vision) | Agent C |
| `backend/app/agents/agent_d.py` | Coverage RAG | Agent D |
| `backend/app/agents/agent_e.py` | CoT decision + HITL | Agent E |
| `backend/app/agents/agent_f.py` | XGBoost judicialization | Agent F |
| `backend/app/agents/agent_g.py` | OFAC fuzzy match + fraud scoring | Agent G |
| `backend/app/agents/agent_h.py` | RAG conversational assistant | Agent H |
| `backend/app/agents/orchestrator.py` | Connect real agents (update stubs) | Lead |
| `frontend/app.py` | Streamlit dashboard with CoT + HITL panel | Frontend |

---

## Task 1: Foundation — requirements, policy doc, OFAC list, ChromaDB pipeline

### 1.1 Update `backend/requirements.txt`

Add after existing entries:
```
faker==25.2.0
reportlab==4.2.2
xgboost==2.0.3
lightgbm==4.3.0
rapidfuzz==3.9.3
scikit-learn==1.5.0
pandas==2.2.2
numpy==1.26.4
shap==0.45.1
sentence-transformers==3.0.1
```

### 1.2 Create `data/policies/poliza_sp_pcs_009.md`

Full synthetic policy document covering SP-PCS-009 claim types, limits, deductibles, exclusions, and required documents. This is the knowledge base for Agents D and H.

### 1.3 Create `data/ofac_mock.json`

Array of 30 fictitious sanctioned names (no real people). Used by Agent G.

### 1.4 Create `backend/app/rag/ingestion.py`

Loads all `.md` files from `data/policies/` into ChromaDB collection `smart_claims_policies` using sentence-transformers embeddings.

Key function: `async def ingest_policies() -> int`

### 1.5 Create `backend/app/rag/retriever.py`

Returns a retriever object for `smart_claims_policies`. Shared by Agents D and H.

Key function: `async def get_coverage_retriever() -> _ChromaRetriever`

### 1.6 Create `data/synthetic/generator.py`

Generates 100 synthetic SP-PCS-009 claims with ground truth. Saves to `data/synthetic/claims_dataset.json`.

Distribution: 60% approve · 25% request_info · 15% reject · 30% HITL

---

## Task 2: Agent B — Document Validation

**File:** `backend/app/agents/agent_b.py`

Required documents by claim type (from SP-PCS-009 + DPA_Requisitos):

```python
REQUIRED_DOCS = {
    "danys_propis": ["formulario_aviso_accidente", "acta_policial", "licencia_conducir",
                     "cedula", "fotos_danos", "cotizacion_taller"],
    "DPA":          ["aviso_siniestro", "acta_policial_certificada", "acta_conciliacion",
                     "presupuesto_piezas", "fotos_danos_con_placa", "matricula",
                     "cedula", "licencia_conducir"],
    "RC":           ["aviso_siniestro", "acta_policial", "cedula",
                     "licencia_conducir", "fotos_danos"],
    "robatori":     ["denuncia_policial", "licencia_conducir", "cedula", "matricula"],
    "danys_mecanics": [],  # Not covered — immediate reject
}
```

Business rules applied:
- R-SP-PCS-09-001: Must meet document requirements for claim type
- R-SP-PCS-09-002: If conductor ≠ policy owner → set `flag_cheque_propietario=True`
- Immediate reject if `claim_type == "danys_mecanics"` (not covered)

After document validation, calls Agent G for early OFAC screening.

Key function: `async def validate_claim_documents(state: ClaimState) -> dict`

---

## Task 3: Agent C — Multimodal Extraction (VLM)

**File:** `backend/app/agents/agent_c.py`

Uses Claude Vision (claude-sonnet-4-20250514) to extract structured data from:
- Vehicle damage photos → `{parts_damaged, severity, estimated_repair_RD}`
- Workshop quotes (PDF/image) → `{items, total, taller_name, date}`
- Police report scans → `{incident_date, location, parties, description, acta_number}`

Key function: `async def extract_from_document(state: ClaimState) -> dict`

Input: `state["extracted_data"]["file_url"]` + `state["extracted_data"]["doc_type"]`
Output: `state["extracted_data"]["c_result"]` with structured JSON

---

## Task 4: Agent D — Coverage RAG

**File:** `backend/app/agents/agent_d.py`

Queries ChromaDB with the claim details, then uses Claude to interpret the policy and determine:
- `covered: bool`
- `max_coverage: float` (RD$)
- `deductible: float` (RD$)
- `net_payable: float` (RD$)
- `policy_section: str`
- `confidence: float` (0–1)

Fallback hardcoded rules if ChromaDB unavailable:
```python
{"danys_propis": {"max": 500_000, "deductible": 5_000},
 "DPA":          {"max": 1_000_000, "deductible": 0},
 "RC":           {"max": 2_000_000, "deductible": 0},
 "robatori":     {"max": 800_000, "deductible": 10_000},
 "danys_mecanics": {"covered": False}}
```

Key function: `async def check_policy_coverage(state: ClaimState) -> dict`

---

## Task 5: Agent E — Decision + HITL

**File:** `backend/app/agents/agent_e.py`

HITL triggers (auto-escalate to human review):
- Amount > RD$500,000
- Coverage confidence < 0.75
- Fraud score > 0.30

If no HITL: runs Chain-of-Thought with Claude to decide:
- `approve` → `RESOLVED` + call `approve_payment`
- `reject` → `REJECTED` + call `send_rejection`
- `request_info` → `VALIDATING` + call `request_more_info`

Key function: `async def decide_claim(state: ClaimState) -> dict`

Constants:
```python
HITL_THRESHOLD_AMOUNT = 500_000       # RD$
HITL_THRESHOLD_CONFIDENCE = 0.75
HITL_THRESHOLD_FRAUD = 0.30
```

---

## Task 6: Agent F — Judicialization XGBoost

**File:** `backend/app/agents/agent_f.py`
**Training:** `data/synthetic/train_agent_f.py`

Features (10):
1. `amount_requested` / 1_000_000 (normalized)
2. `prior_claims_count`
3. `days_since_incident`
4. `interaction_count`
5. `proposal_rejected_before` (0/1)
6. `claim_type_RC` (0/1)
7. `claim_type_DPA` (0/1)
8. `claim_type_danys_propis` (0/1)
9. `risk_score` (from Agent G)
10. `channel_phone` (0/1)

Label: `judicializado` (0/1) — target ~10% positive rate

Risk levels: HIGH (>60%) → MEDIUM (>30%) → LOW

Key function: `async def predict_judicialization_risk(state: ClaimState) -> dict`

If model not trained yet: heuristic fallback active.

---

## Task 7: Agent G — Fraud + AML/CFT

**File:** `backend/app/agents/agent_g.py`

Step 1: Fuzzy matching (rapidfuzz `token_sort_ratio >= 85`) against `data/ofac_mock.json`
- Checks both `client_name` and `conductor_name`
- Any match → `is_flagged=True` → HITL immediate

Step 2: Heuristic fraud score (0.0–1.0) based on PEPIN-POL-CP-0006:
- Amount > RD$500,000 for danys_propis: +0.20
- prior_claims ≥ 3: +0.25 | ≥ 2: +0.10
- Incident between 00:00–05:00: +0.15
- Incomplete documents: +0.10

Due diligence level:
- `ampliada` if flagged OR score > 0.50
- `simplificada` otherwise

Key function: `async def check_fraud_and_compliance(state: ClaimState) -> dict`

---

## Task 8: Agent H — RAG Conversational Assistant

**File:** `backend/app/agents/agent_h.py`

Shares ChromaDB collection with Agent D. Answers natural-language questions from inspectors/lawyers about policies, procedures, and the current case.

Indexed documents (all from `data/policies/`):
- `poliza_sp_pcs_009.md`
- `ficha_sp_pcs_009.md` (copy from source docs)
- `ficha_sp_pcs_022.md`
- `ficha_sp_pcs_003.md`
- `politica_dda.md`

Key function: `async def answer_expert_query(state: ClaimState) -> dict`

Input: `state["extracted_data"]["h_query"]`
Output: `state["extracted_data"]["h_result"]` + `h_sources`

---

## Task 9: Update Orchestrator

**File:** `backend/app/agents/orchestrator.py`

Replace `_stub()` functions with real agent imports:
```python
from app.agents.agent_b import validate_claim_documents
from app.agents.agent_c import extract_from_document
from app.agents.agent_d import check_policy_coverage
from app.agents.agent_e import decide_claim
from app.agents.agent_f import predict_judicialization_risk
from app.agents.agent_g import check_fraud_and_compliance
from app.agents.agent_h import answer_expert_query
```

Full flow: triage → B → G (early) → C → D → G (fraud score) → F → E → HITL?

---

## Task 10: Streamlit Dashboard

**File:** `frontend/app.py`

Pages:
1. **Nueva Reclamación** — form to submit a claim, shows CoT output in real time
2. **Cola HITL** — list of claims pending human review with approve/reject buttons
3. **Dashboard KPIs** — KPI1 (avg days), KPI2 (judicialization rate), KPI3 (automation %)
4. **Consulta Agente H** — chat interface for inspector/lawyer queries

Fix typo `st.titgle` → `st.title` immediately.
