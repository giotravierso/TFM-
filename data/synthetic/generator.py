"""
Synthetic SP-PCS-009 claims dataset generator for Smart-Claims Agent PoC.

Produces 100 insurance claims with ground-truth labels for training and
evaluating agents B–H.  No real data — all names, amounts and incidents are
fictitious.

Usage (inside Docker or local venv with faker installed):
    python data/synthetic/generator.py
Output: data/synthetic/claims_dataset.json
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

# ── Constants ─────────────────────────────────────────────────────────────────

SEED = 42
N_CLAIMS = 100
OUTPUT_PATH = Path(__file__).parent / "claims_dataset.json"
OFAC_PATH = Path(__file__).parent.parent / "ofac_mock.json"

CLAIM_TYPES: list[tuple[str, int]] = [
    ("danys_propis",    40),
    ("DPA",             30),
    ("RC",              15),
    ("robatori",        10),
    ("danys_mecanics",   5),
]

REQUIRED_DOCS: dict[str, list[str]] = {
    "danys_propis": [
        "formulario_aviso_accidente", "acta_policial",
        "licencia_conducir", "cedula", "fotos_danos", "cotizacion_taller",
    ],
    "DPA": [
        "aviso_siniestro", "acta_policial_certificada", "acta_conciliacion",
        "presupuesto_piezas", "fotos_danos_con_placa", "matricula",
        "cedula", "licencia_conducir",
    ],
    "RC": [
        "aviso_siniestro", "acta_policial",
        "cedula", "licencia_conducir", "fotos_danos",
    ],
    "robatori": [
        "denuncia_policial", "licencia_conducir", "cedula", "matricula",
    ],
    "danys_mecanics": [],
}

COVERAGE: dict[str, dict] = {
    "danys_propis":   {"max": 500_000,   "deductible": 5_000,  "covered": True},
    "DPA":            {"max": 1_000_000, "deductible": 0,       "covered": True},
    "RC":             {"max": 2_000_000, "deductible": 0,       "covered": True},
    "robatori":       {"max": 800_000,   "deductible": 10_000,  "covered": True},
    "danys_mecanics": {"max": 0,         "deductible": 0,       "covered": False},
}

HITL_AMOUNT_THRESHOLD = 500_000

VEHICLES: list[tuple[str, str]] = [
    ("Toyota", "Corolla"), ("Toyota", "Yaris"), ("Toyota", "Hilux"),
    ("Hyundai", "Tucson"), ("Hyundai", "Elantra"),
    ("Kia", "Sportage"), ("Kia", "Cerato"),
    ("Jetour", "T1 Lux"), ("Jetour", "T2 Plus"),
    ("Mitsubishi", "Outlander"), ("Nissan", "Sentra"),
    ("Honda", "CR-V"), ("Chevrolet", "Trax"),
    ("Ford", "Explorer"), ("BMW", "X3"),
    ("Volkswagen", "Polo"), ("Mazda", "CX-5"),
]

LOCATIONS: list[str] = [
    "Av. Abraham Lincoln, Santo Domingo",
    "Av. 27 de Febrero, Santo Domingo",
    "Av. John F. Kennedy, Santo Domingo",
    "Av. Máximo Gómez, Santo Domingo",
    "Av. Winston Churchill, Santo Domingo",
    "Carretera Duarte, Santiago",
    "Av. Las Carreras, Santiago",
    "Autopista Duarte, km 15",
    "Carretera Sánchez, Baní",
    "Av. Independencia, Santo Domingo",
    "Carretera Mella, Santo Domingo Este",
    "Av. San Martín, Santo Domingo",
    "Av. Rómulo Betancourt, Santo Domingo",
    "Av. España, Santo Domingo Este",
    "Malecón, Santo Domingo",
]

TALLERES: list[str] = [
    "Auto Center Pepín",
    "Talleres Moca Express",
    "Centro Automotriz del Este",
    "TechCar Santiago",
    "Grupo Automotriz RD",
    "Auto Pro Santo Domingo",
    "Taller Hernández e Hijos",
    "Repuestos y Servicio Continental",
]

CHANNELS: list[str] = ["email", "phone", "presencial"]

PLATE_PREFIXES: list[str] = ["PP", "A", "B", "C", "D", "E", "G", "H"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _plate(rng: random.Random) -> str:
    return f"{rng.choice(PLATE_PREFIXES)}{rng.randint(10000, 99999)}"


def _net_payable(claim_type: str, amount: float) -> float:
    cov = COVERAGE[claim_type]
    if not cov["covered"]:
        return 0.0
    return max(0.0, min(amount, cov["max"]) - cov["deductible"])


def _fraud_score(
    claim_type: str,
    amount: float,
    prior_claims: int,
    incident_hour: int,
    docs_complete: bool,
) -> float:
    score = 0.0
    if claim_type == "danys_propis" and amount > 500_000:
        score += 0.20
    if prior_claims >= 3:
        score += 0.25
    elif prior_claims >= 2:
        score += 0.10
    if 0 <= incident_hour < 5:
        score += 0.15
    if not docs_complete:
        score += 0.10
    return round(min(score, 1.0), 3)


def _confidence(claim_type: str, amount: float, docs_complete: bool, prior_claims: int) -> float:
    if claim_type == "danys_mecanics":
        return 0.99  # certain rejection
    base = 0.90 if docs_complete else 0.62
    if amount > COVERAGE[claim_type]["max"]:
        base -= 0.08
    if prior_claims >= 2:
        base -= 0.05
    return round(max(0.50, min(base, 0.99)), 3)


def _decide(
    claim_type: str,
    net_pay: float,
    docs_complete: bool,
    fraud_score: float,
    confidence: float,
    ofac_flagged: bool,
) -> tuple[str, bool]:
    """Return (decision, hitl_required) per SP-PCS-009 §3.3 rules."""
    if claim_type == "danys_mecanics":
        return "reject", False
    if ofac_flagged:
        return "hitl", True
    if net_pay > HITL_AMOUNT_THRESHOLD:
        return "hitl", True
    if fraud_score > 0.30:
        return "hitl", True
    if confidence < 0.75 or not docs_complete:
        return "request_info", False
    return "approve", False


def _description(
    claim_type: str,
    brand: str,
    model: str,
    plate: str,
    location: str,
    rng: random.Random,
) -> str:
    templates: dict[str, list[str]] = {
        "danys_propis": [
            f"Colisión frontal del {brand} {model} placa {plate} en {location}.",
            f"Vuelco del {brand} {model} ({plate}) al perder el control en {location}.",
            f"Choque contra poste de alumbrado en {location}. {brand} {model} placa {plate}.",
            f"Impacto en parte trasera del {brand} {model} placa {plate} en {location}.",
        ],
        "DPA": [
            f"El {brand} {model} placa {plate} causó daños a propiedad de tercero en {location}.",
            f"Colisión en {location}: {brand} {model} ({plate}) impactó vehículo estacionado.",
            f"Asegurado con {brand} {model} placa {plate} causó daños materiales a tercero en {location}.",
        ],
        "RC": [
            f"Reclamación RC por accidente en {location} con {brand} {model} placa {plate}.",
            f"Tercero afectado por accidente causado por {brand} {model} ({plate}) en {location}.",
        ],
        "robatori": [
            f"Robo total del {brand} {model} placa {plate} reportado en {location}.",
            f"Sustracción del {brand} {model} ({plate}). Denuncia ante Policía Nacional.",
            f"Hurto parcial de piezas del {brand} {model} placa {plate} estacionado en {location}.",
        ],
        "danys_mecanics": [
            f"Falla mecánica en motor del {brand} {model} placa {plate}. Solicita cobertura por avería.",
            f"Daño por desgaste en transmisión del {brand} {model} ({plate}). No derivado de accidente.",
        ],
    }
    return rng.choice(templates[claim_type])


# ── Generator ─────────────────────────────────────────────────────────────────

def generate_claims(n: int = N_CLAIMS) -> list[dict]:
    rng = random.Random(SEED)
    fake = Faker(["es_ES"])
    fake.seed_instance(SEED)

    ofac_list: list[str] = json.loads(OFAC_PATH.read_text(encoding="utf-8"))

    # Build type pool respecting fixed counts
    type_pool: list[str] = []
    for ctype, count in CLAIM_TYPES:
        type_pool.extend([ctype] * count)
    rng.shuffle(type_pool)

    claims: list[dict] = []
    for idx, claim_type in enumerate(type_pool):
        claim_id = f"EXP-2026-{idx + 1:04d}"

        # Parties
        client_name = fake.name().upper()
        conductor_is_owner = rng.random() < 0.85
        conductor_name = client_name if conductor_is_owner else fake.name().upper()

        # OFAC flag (~5 % of claims)
        ofac_flagged = False
        if rng.random() < 0.05:
            conductor_name = rng.choice(ofac_list)
            ofac_flagged = True

        # Vehicle
        brand, model = rng.choice(VEHICLES)
        year = rng.randint(2015, 2024)
        plate = _plate(rng)
        policy_number = f"SP-PCS-009-{rng.randint(10000, 99999)}"

        # Dates
        incident_date = date(2026, 1, 1) + timedelta(days=rng.randint(0, 141))
        incident_hour = rng.randint(0, 23)
        incident_minute = rng.choice([0, 15, 30, 45])
        days_since = max(0, (date(2026, 5, 23) - incident_date).days)

        # Amount requested
        if claim_type == "danys_propis":
            amount = round(rng.uniform(8_000, 620_000), -2)
        elif claim_type == "DPA":
            amount = round(rng.uniform(15_000, 1_150_000), -2)
        elif claim_type == "RC":
            amount = round(rng.uniform(30_000, 2_200_000), -2)
        elif claim_type == "robatori":
            amount = round(rng.uniform(100_000, 860_000), -2)
        else:  # danys_mecanics
            amount = round(rng.uniform(5_000, 80_000), -2)

        net_pay = _net_payable(claim_type, amount)

        # History
        prior_claims = rng.choices([0, 1, 2, 3, 4], weights=[50, 30, 12, 5, 3])[0]
        interaction_count = rng.randint(1, 9)
        proposal_rejected = rng.random() < 0.10

        # Documents
        required = REQUIRED_DOCS[claim_type]
        if required and rng.random() < 0.80:
            submitted = required.copy()
            docs_complete = True
        elif required:
            n_missing = rng.randint(1, min(2, len(required)))
            submitted = rng.sample(required, len(required) - n_missing)
            docs_complete = False
        else:
            submitted = []
            docs_complete = True  # mechanical: nothing required, auto-reject anyway

        # Channel
        channel = rng.choices(CHANNELS, weights=[40, 35, 25])[0]

        # Scoring
        fscore = _fraud_score(claim_type, amount, prior_claims, incident_hour, docs_complete)
        conf = _confidence(claim_type, amount, docs_complete, prior_claims)

        # Ground-truth decision
        decision, hitl_required = _decide(
            claim_type, net_pay, docs_complete, fscore, conf, ofac_flagged
        )

        # Judicialization risk (~10 % positive rate)
        judi_prob = 0.04
        if claim_type in ("RC", "DPA"):
            judi_prob += 0.06
        if amount > 300_000:
            judi_prob += 0.05
        if proposal_rejected:
            judi_prob += 0.12
        if interaction_count > 5:
            judi_prob += 0.05
        if days_since > 30:
            judi_prob += 0.03
        judicializado = rng.random() < min(judi_prob, 0.45)

        # Optional fields
        taller = rng.choice(TALLERES) if claim_type in ("danys_propis", "DPA") else None
        location = rng.choice(LOCATIONS)
        acta_number = (
            f"Q-{rng.randint(100000, 999999)}-26" if claim_type != "danys_mecanics" else None
        )

        claims.append({
            "claim_id": claim_id,
            "claim_type": claim_type,
            "policy_number": policy_number,
            "client_name": client_name,
            "conductor_name": conductor_name,
            "conductor_is_owner": conductor_is_owner,
            "vehicle": {
                "brand": brand,
                "model": model,
                "year": year,
                "plate": plate,
            },
            "incident": {
                "date": incident_date.isoformat(),
                "time": f"{incident_hour:02d}:{incident_minute:02d}",
                "location": location,
                "acta_number": acta_number,
                "description": _description(claim_type, brand, model, plate, location, rng),
            },
            "financials": {
                "amount_requested": amount,
                "max_coverage": COVERAGE[claim_type]["max"],
                "deductible": COVERAGE[claim_type]["deductible"],
                "covered": COVERAGE[claim_type]["covered"],
                "net_payable": net_pay,
            },
            "documents": {
                "required": required,
                "submitted": submitted,
                "complete": docs_complete,
            },
            "history": {
                "prior_claims_count": prior_claims,
                "interaction_count": interaction_count,
                "proposal_rejected_before": proposal_rejected,
                "days_since_incident": days_since,
            },
            "channel": channel,
            "taller": taller,
            "compliance": {
                "fraud_score": fscore,
                "confidence": conf,
                "ofac_flagged": ofac_flagged,
                "due_diligence": (
                    "ampliada" if (ofac_flagged or fscore > 0.50) else "simplificada"
                ),
            },
            "ground_truth": {
                "decision": decision,
                "hitl_required": hitl_required,
                "judicializado": judicializado,
            },
        })

    return claims


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    claims = generate_claims()
    OUTPUT_PATH.write_text(
        json.dumps(claims, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    decisions = [c["ground_truth"]["decision"] for c in claims]
    hitl_n = sum(1 for c in claims if c["ground_truth"]["hitl_required"])
    judi_n = sum(1 for c in claims if c["ground_truth"]["judicializado"])
    ofac_n = sum(1 for c in claims if c["compliance"]["ofac_flagged"])

    print(f"Generated {len(claims)} claims -> {OUTPUT_PATH}")
    for d in ("approve", "request_info", "reject", "hitl"):
        cnt = decisions.count(d)
        print(f"  {d:<15} {cnt:3d}  ({cnt / len(claims):.0%})")
    print(f"  HITL required   {hitl_n:3d}  ({hitl_n / len(claims):.0%})")
    print(f"  Judicializado   {judi_n:3d}  ({judi_n / len(claims):.0%})")
    print(f"  OFAC flagged    {ofac_n:3d}  ({ofac_n / len(claims):.0%})")


if __name__ == "__main__":
    main()
