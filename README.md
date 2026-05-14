# Smart-Claims Agent

> **TFM — Máster en Machine Learning e Inteligencia Artificial**
> OBS Business School · Edición 2510
> Empresa de referencia: Seguros Pepín, S.A.

Sistema agéntico de procesamiento multimodal y ejecución autónoma para la gestión de reclamaciones de siniestros. El agente integra LLMs con capacidades de visión (VLM), razonamiento ReAct y recuperación semántica (RAG) para automatizar el ciclo completo de una reclamación: recepción, validación documental, verificación de cobertura, detección de fraude y resolución autónoma.

---

## Tabla de contenidos

1. [Arquitectura del sistema](#1-arquitectura-del-sistema)
2. [Stack tecnológico](#2-stack-tecnológico)
3. [Estructura del repositorio](#3-estructura-del-repositorio)
4. [Prerrequisitos](#4-prerrequisitos)
5. [Configuración del entorno](#5-configuración-del-entorno)
6. [Puesta en marcha con Docker](#6-puesta-en-marcha-con-docker)
7. [Servicios y URLs](#7-servicios-y-urls)
8. [Agentes implementados](#8-agentes-implementados)
9. [Base de datos](#9-base-de-datos)
10. [RAG y base de conocimiento](#10-rag-y-base-de-conocimiento)
11. [Mock APIs](#11-mock-apis)
12. [Frontend Streamlit](#12-frontend-streamlit)
13. [Testing](#13-testing)
14. [Flujo de trabajo del equipo](#14-flujo-de-trabajo-del-equipo)
15. [Variables de entorno](#15-variables-de-entorno)
16. [Decisiones de diseño](#16-decisiones-de-diseño)
17. [Registro de cambios](#17-registro-de-cambios)

---

## 1. Arquitectura del sistema

El sistema se organiza en cinco capas funcionales orquestadas por LangGraph con patrón ReAct (Reason → Act → Observe):

```
┌─────────────────────────────────────────────────────────────────┐
│  CAPA 1 — Canales de entrada                                    │
│  Email · Portal web · WhatsApp (simulado) · API REST            │
└───────────────────────┬─────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│  CAPA 2 — Orquestación (Agente A)                               │
│  LangGraph + ReAct · Gestión de estado por expediente           │
│  Router de agentes · Human-in-the-Loop (HITL)                   │
└───────┬───────┬───────┬──────────┬───────────┬──────────────────┘
        │       │       │          │           │
       [B]     [C]     [D]        [E]         [G]
        │       │       │          │           │
┌───────▼───────▼───────▼──────────▼───────────▼──────────────────┐
│  CAPA 3 — Agentes especializados                                 │
│  B: Validación documental    C: Extracción VLM                  │
│  D: Cobertura RAG            E: Resolución autónoma             │
│  G: Fraude y cumplimiento                                        │
└───────────────────────┬─────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│  CAPA 4 — Datos y conocimiento                                  │
│  ChromaDB (pólizas, RAG) · MariaDB (log decisiones, HITL)       │
└───────────────────────┬─────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│  CAPA 5 — Integración simulada                                  │
│  Mock APIs Python: pagos · notificaciones · sistemas legacy      │
└─────────────────────────────────────────────────────────────────┘

  TRANSVERSAL T1: Seguridad (anonimización, control de acceso, auditoría)
  TRANSVERSAL T2: Observabilidad (trazas CoT, métricas, dashboard Streamlit)
```

### Flujo de una reclamación

```
Cliente envía reclamación
        │
        ▼
[A] Orquestador — triaje y enrutamiento
        │
        ├──► [G] Verificación OFAC/fraude (filtro temprano)
        │
        ├──► [B] Validación documental
        │         └── ¿Faltan documentos? → solicitar al cliente
        │
        ├──► [C] Extracción VLM (fotos, facturas, actas)
        │
        ├──► [D] Verificación de cobertura via RAG
        │
        └──► [E] Decisión autónoma
                  ├── Importe ≤ umbral → PAGO automático
                  ├── Importe > umbral → HITL (revisión humana)
                  └── Sin cobertura   → RECHAZO justificado
```

---

## 2. Stack tecnológico

| Componente | Tecnología | Versión |
|---|---|---|
| LLM / VLM | Claude (Anthropic) | claude-sonnet-4-20250514 |
| Framework agéntico | LangGraph + LangChain | 0.1.14 / 0.2.6 |
| Vector DB (RAG) | ChromaDB | 0.5.3 |
| Base de datos | MariaDB | 11.3 |
| Backend API | FastAPI + Uvicorn | 0.111.0 |
| Frontend demo | Streamlit | 1.36.0 |
| Lenguaje | Python | 3.11 |
| Contenerización | Docker + Compose | 25+ / 2.24+ |
| ORM | SQLAlchemy + Alembic | 2.0.31 |
| OCR (fallback) | Tesseract | sistema |

---

## 3. Estructura del repositorio

```
smart-claims-agent/
│
├── docker-compose.yml          # Orquestación de los 5 servicios
├── .env.example                # Plantilla de variables de entorno
├── .env                        # Variables reales (NO commitear)
├── .gitignore
├── setup.sh                    # Script de inicialización
├── README.md                   # Este documento
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py             # Entrypoint FastAPI
│   │   ├── agents/
│   │   │   ├── orchestrator.py # Agente A — LangGraph ReAct
│   │   │   ├── agent_b.py      # Validación documental
│   │   │   ├── agent_c.py      # Extracción multimodal VLM
│   │   │   ├── agent_d.py      # Verificación cobertura RAG
│   │   │   ├── agent_e.py      # Resolución autónoma
│   │   │   └── agent_g.py      # Fraude y cumplimiento
│   │   ├── tools/
│   │   │   └── claim_tools.py  # Mock APIs (tools del agente)
│   │   ├── rag/
│   │   │   ├── ingest.py       # Ingesta de pólizas a ChromaDB
│   │   │   └── retriever.py    # Retriever semántico
│   │   ├── db/
│   │   │   ├── models.py       # Modelos SQLAlchemy
│   │   │   └── session.py      # Gestión de conexión
│   │   └── routers/
│   │       ├── claims.py       # POST /api/v1/claims
│   │       ├── agents.py       # GET  /api/v1/agents/status
│   │       └── health.py       # GET  /health
│   └── db/
│       └── init.sql            # Schema inicial + seed de demo
│
├── frontend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py                  # Dashboard Streamlit
│
├── data/
│   ├── synthetic/              # Dataset sintético de siniestros (.json)
│   └── policies/               # Documentos de pólizas para RAG (.pdf/.txt)
│
├── scripts/
│   ├── seed_dataset.py         # Genera el dataset sintético
│   └── ingest_policies.py      # Ingesta pólizas en ChromaDB
│
└── tests/
    ├── test_agents.py
    ├── test_tools.py
    └── test_rag.py
```

---

## 4. Prerrequisitos

### Software necesario

| Herramienta | Versión mínima | Verificación |
|---|---|---|
| Docker Desktop | 25.0 | `docker --version` |
| Docker Compose | 2.24 | `docker compose version` |
| Git | 2.40 | `git --version` |
| VSCode | cualquiera | — |
| Extensión WSL (si usas Windows) | — | Marketplace de VSCode |

### Clave de API

Necesitas una clave de la API de Anthropic. Puedes obtenerla en [console.anthropic.com](https://console.anthropic.com).

### Importante: dónde instalar el proyecto (Windows + WSL)

Si trabajas en **Windows con WSL2**, instala el proyecto **dentro del filesystem de Linux**, no en `/mnt/c/...`. El rendimiento de Docker con volúmenes montados sobre el filesystem de Windows es muy bajo (hot-reload lento, inotify fallando).

```bash
# ✅ Correcto — dentro de WSL
/home/tu_usuario/proyectos/TFM/smart-claims-agent/

# ❌ Incorrecto — filesystem de Windows montado en WSL
/mnt/c/Users/tu_usuario/proyectos/TFM/
```

Para abrir el proyecto en VSCode desde WSL:

```bash
cd ~/proyectos/TFM/smart-claims-agent
code .   # Abre VSCode conectado a WSL (requiere extensión WSL)
```

---

## 5. Configuración del entorno

### 5.1 Clonar el repositorio

```bash
git clone https://github.com/[org]/smart-claims-agent.git
cd smart-claims-agent
```

### 5.2 Crear el fichero de variables de entorno

```bash
cp .env.example .env
```

Edita `.env` y rellena como mínimo:

```bash
ANTHROPIC_API_KEY=sk-ant-api03-...   # Obligatorio
DB_ROOT_PASSWORD=root_dev             # Puedes dejarlo así en dev
DB_PASSWORD=claims_dev                # Puedes dejarlo así en dev
```

El resto de variables ya apuntan a los nombres de los contenedores Docker y no necesitan modificarse en desarrollo.

> ⚠️ **Nunca commitees el fichero `.env`**. Está incluido en `.gitignore`.

### 5.3 Crear ficheros necesarios que no genera Git

Git no versiona directorios vacíos ni ficheros `__init__.py`. Ejecuta este bloque una sola vez tras clonar:

```bash
# __init__.py para que Python reconozca los módulos
touch backend/app/__init__.py \
      backend/app/agents/__init__.py \
      backend/app/tools/__init__.py \
      backend/app/rag/__init__.py \
      backend/app/db/__init__.py \
      backend/app/routers/__init__.py

# Directorios de datos (vacíos intencionadamente hasta ejecutar los scripts)
mkdir -p data/synthetic data/policies tests scripts
```

### 5.4 Verificar que Docker Desktop ve WSL (solo Windows)

Abre Docker Desktop → Settings → Resources → WSL Integration → activa tu distribución de Ubuntu.

Verifica desde WSL:

```bash
docker info | grep "Operating System"
# Debe mostrar: Operating System: Docker Desktop

docker context ls
# El contexto activo (*) debe ser: desktop-linux
```

---

## 6. Puesta en marcha con Docker

### Primera vez

```bash
# Construye las imágenes (3-5 minutos la primera vez)
docker compose build

# Arranca todos los servicios en segundo plano
docker compose up -d

# Verifica que todos están en ejecución
docker compose ps
```

La salida esperada de `docker compose ps`:

```
NAME            STATUS                   PORTS
sca-adminer     running                  0.0.0.0:8082->8080/tcp
sca-backend     running                  0.0.0.0:8000->8000/tcp
sca-chromadb    running                  0.0.0.0:8080->8000/tcp
sca-frontend    running                  0.0.0.0:8501->8501/tcp
sca-mariadb     running (healthy)        0.0.0.0:3306->3306/tcp
```

> El backend espera a que MariaDB pase el `healthcheck` antes de arrancar. Si ves el backend reiniciándose los primeros 20-30 segundos, es normal.

### Verificación rápida

```bash
# API responde
curl http://localhost:8000/health
# {"status":"ok","version":"0.2.0"}

# Swagger UI
open http://localhost:8000/docs   # macOS
xdg-open http://localhost:8000/docs   # Linux/WSL
```

### Comandos del día a día

```bash
# Ver logs de todos los servicios (Ctrl+C para salir)
docker compose logs -f

# Ver logs solo del backend
docker compose logs -f backend

# Parar todos los servicios (conserva los datos)
docker compose down

# Parar y eliminar también los volúmenes de datos ⚠️
docker compose down -v

# Reconstruir un servicio tras cambiar requirements.txt o Dockerfile
docker compose up -d --build backend

# Ejecutar un comando dentro del contenedor backend
docker exec -it sca-backend python scripts/seed_dataset.py

# Conectarse a la base de datos desde terminal
docker exec -it sca-mariadb mariadb -u claims_user -pclaims_dev smart_claims
```

### Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| Backend: `Can't connect to MySQL` | MariaDB aún inicializando | Esperar 20-30 s o `docker compose logs mariadb` |
| Puerto 3306 ocupado | MySQL/MariaDB local corriendo | `sudo systemctl stop mysql` o cambiar puerto en compose |
| `ModuleNotFoundError` en backend | Falta `__init__.py` o paquete | Ejecutar bloque del paso 5.3 y `docker compose up -d --build backend` |
| Hot-reload muy lento | Proyecto en `/mnt/c/...` | Mover el proyecto al filesystem de WSL |
| ChromaDB pierde datos | Se usó `down -v` | Evitar `-v`; los datos viven en el volumen `sca_chromadb_data` |

---

## 7. Servicios y URLs

| Servicio | URL | Credenciales |
|---|---|---|
| **API REST** (Swagger UI) | http://localhost:8000/docs | — |
| **Frontend** (Streamlit) | http://localhost:8501 | — |
| **ChromaDB** (API) | http://localhost:8080 | — |
| **Adminer** (explorador DB) | http://localhost:8082 | servidor: `mariadb` · usuario: `claims_user` · pass: `claims_dev` · BD: `smart_claims` |

---

## 8. Agentes implementados

### Agente A — Orquestador (LangGraph ReAct)

**Fichero:** `backend/app/agents/orchestrator.py`

Cerebro central del sistema. Recibe la reclamación, analiza el contenido y decide qué agente especializado debe intervenir en cada paso. Gestiona el estado de cada expediente a lo largo de todo el flujo y activa el mecanismo HITL cuando el importe supera el umbral configurado.

- **Patrón:** ReAct (Reason → Act → Observe → Reason...)
- **Estado:** `ClaimState` (TypedDict con LangGraph)
- **HITL:** se activa cuando `amount > HITL_AMOUNT_THRESHOLD` (variable de entorno)

### Agente B — Validación documental

**Fichero:** `backend/app/agents/agent_b.py` *(pendiente)*

Verifica que el cliente tiene contrato vigente y que ha aportado todos los documentos requeridos. Antes de invocar al Agente C, llama al Agente G para el cribado OFAC temprano. Tiene autonomía para solicitar documentación adicional directamente al cliente.

**Pain points que resuelve:** dependencia de procesos manuales · controles no integrados · informalidad en la gestión de información.

### Agente C — Extracción multimodal (VLM)

**Fichero:** `backend/app/agents/agent_c.py` *(pendiente)*

Extrae datos estructurados de documentos e imágenes usando Claude con capacidades de visión. Procesa facturas (importe, fecha, proveedor), fotografías de daños (tipo, severidad, estimación de reparación) y actas policiales. Incluye fallback a OCR clásico (Tesseract) para documentos de baja calidad.

**Pain points que resuelve:** subjetividad en la evaluación técnica · dependencia de procesos manuales en transcripción.

### Agente D — Verificación de cobertura (RAG)

**Fichero:** `backend/app/agents/agent_d.py` *(pendiente)*

Consulta la base de conocimiento vectorial (ChromaDB) con las pólizas y procedimientos de Seguros Pepín para determinar si el tipo de siniestro está cubierto, el importe máximo y la franquicia aplicable. Devuelve el importe neto a pagar.

**Pain points que resuelve:** subjetividad en evaluación · falta de criterios estandarizados · controles manuales.

### Agente E — Resolución autónoma

**Fichero:** `backend/app/agents/agent_e.py` *(pendiente)*

Toma la decisión final basándose en el output de los agentes anteriores: aprobar pago, rechazar con justificación o solicitar más información. Ejecuta la acción a través de las Mock APIs y registra el razonamiento completo (Chain of Thought) en MariaDB.

**Reglas de decisión:**
- Cubierto + importe ≤ umbral HITL → pago automático
- Cubierto + importe > umbral HITL → pausa para revisión humana
- No cubierto → rechazo con motivo detallado
- Documentación incompleta → solicitud de información

### Agente G — Fraude y cumplimiento (LA/FT)

**Fichero:** `backend/app/agents/agent_g.py` *(pendiente)*

Verifica al cliente contra listas restrictivas (OFAC, ONU) y calcula un score de riesgo de fraude. Se invoca como **filtro de entrada** (tras el Agente B), no al final del flujo, alineándose con la política PEPIN-POL-CP-0006.

**Pain points que resuelve:** compliance como filtro de salida en lugar de entrada · brecha en debida diligencia temprana.

---

## 9. Base de datos

### Schema (MariaDB 11.3)

**`claims`** — Expedientes de reclamación

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | VARCHAR(36) | ID del expediente (PK) |
| `client_id` | VARCHAR(64) | Identificador del cliente |
| `claim_type` | VARCHAR(64) | Tipo de siniestro |
| `channel` | ENUM | Canal de entrada (email/web/whatsapp) |
| `status` | ENUM | Estado actual del expediente |
| `amount_requested` | DECIMAL | Importe reclamado |
| `amount_approved` | DECIMAL | Importe finalmente aprobado |

**`agent_decisions`** — Log de decisiones (Chain of Thought)

| Campo | Tipo | Descripción |
|---|---|---|
| `claim_id` | VARCHAR(36) | FK → claims |
| `agent` | VARCHAR(32) | Identificador del agente (agent_a ... agent_g) |
| `action` | VARCHAR(128) | Acción ejecutada |
| `reasoning` | TEXT | Razonamiento completo CoT |
| `confidence` | FLOAT | Nivel de confianza del agente |
| `hitl_required` | BOOLEAN | Si requirió revisión humana |

**`hitl_feedback`** — Feedback del revisor humano

| Campo | Tipo | Descripción |
|---|---|---|
| `decision_id` | BIGINT | FK → agent_decisions |
| `reviewer` | VARCHAR(128) | Identificador del revisor |
| `original_action` | VARCHAR(128) | Decisión original del agente |
| `final_action` | VARCHAR(128) | Decisión final tras revisión |
| `override_reason` | TEXT | Motivo del cambio (si aplica) |

### Acceso directo a la BD

```bash
# Desde terminal
docker exec -it sca-mariadb mariadb -u claims_user -pclaims_dev smart_claims

# Consultas útiles para debug
SELECT id, status, amount_requested FROM claims;
SELECT claim_id, agent, action, confidence FROM agent_decisions ORDER BY created_at DESC LIMIT 20;
SELECT * FROM hitl_feedback;
```

### Migraciones (Alembic)

```bash
# Crear una nueva migración tras cambiar models.py
docker exec -it sca-backend alembic revision --autogenerate -m "descripcion"

# Aplicar migraciones pendientes
docker exec -it sca-backend alembic upgrade head

# Ver estado actual
docker exec -it sca-backend alembic current
```

---

## 10. RAG y base de conocimiento

### Documentos que se ingresan

Los documentos de pólizas y procedimientos se colocan en `data/policies/` y se ingresan a ChromaDB mediante el script de ingesta. Formatos soportados: `.pdf`, `.txt`.

Documentos de referencia del proyecto:
- `SP-PCS-009` — Procedimiento reclamación estándar
- `SP-PCS-022` — Reclamación judicializada
- `SP-PCS-003` — Fianzas judiciales
- `PEPIN-POL-CP-0006` — Política de debida diligencia

### Ingesta inicial

```bash
# Coloca los PDFs de pólizas en data/policies/
# Luego ejecuta la ingesta:
docker exec -it sca-backend python scripts/ingest_policies.py

# Verifica que se han indexado correctamente
curl http://localhost:8080/api/v1/collections
```

### Colección ChromaDB

- **Nombre:** `pepin_policies` (configurable en `.env` con `CHROMA_COLLECTION`)
- **Embedding model:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (multilingüe, soporta español)
- **Chunk size:** 512 tokens con 50 de solapamiento

---

## 11. Mock APIs

**Fichero:** `backend/app/tools/claim_tools.py`

Las Mock APIs simulan las integraciones con sistemas externos. En la Fase II del proyecto (producción) se sustituirían por integraciones reales.

| Tool | Descripción |
|---|---|
| `validate_documents` | Verifica documentación aportada y contrato vigente |
| `extract_multimodal` | Extrae datos de imágenes y documentos via VLM |
| `check_policy` | Consulta cobertura y límites via RAG |
| `approve_payment` | Simula emisión de transferencia bancaria |
| `send_rejection` | Simula envío de email de rechazo justificado |
| `request_more_info` | Simula solicitud de documentación adicional |
| `check_fraud` | Verifica listas OFAC y calcula score de riesgo |
| `log_decision` | Registra decisión y razonamiento en MariaDB |

Todas las tools están decoradas con `@tool` de LangChain y son invocables directamente por el LLM a través de function calling.

---

## 12. Frontend Streamlit

**Fichero:** `frontend/app.py`

El dashboard de demostración muestra en tiempo real:

- Formulario de entrada de una reclamación (texto + adjuntos simulados)
- **Chain of Thought visible**: cada paso de razonamiento del orquestador
- Estado del expediente con timeline de agentes
- Decisión final con justificación
- Panel HITL para validación humana (cuando aplica)
- Métricas de sesión: tiempo de resolución, agentes invocados, confianza media

Para desarrollo del frontend sin tocar el backend:

```bash
# Hot-reload automático: los cambios en frontend/app.py se reflejan al guardar
docker compose logs -f frontend
```

---

## 13. Testing

```bash
# Ejecutar todos los tests
docker exec -it sca-backend pytest tests/ -v

# Solo tests de agentes
docker exec -it sca-backend pytest tests/test_agents.py -v

# Con cobertura
docker exec -it sca-backend pytest tests/ --cov=app --cov-report=term-missing

# Test de un caso de siniestro completo (E2E)
docker exec -it sca-backend pytest tests/test_e2e.py -v -s
```

### Casos de prueba del dataset sintético

El dataset sintético en `data/synthetic/` incluye los siguientes escenarios:

| Escenario | Resultado esperado |
|---|---|
| Daños propios + docs completos + importe bajo | Pago automático |
| Daños propios + docs completos + importe alto | HITL activado |
| Tipo de siniestro no cubierto | Rechazo justificado |
| Documentación incompleta | Solicitud de información |
| Cliente en lista OFAC | Bloqueo en filtro temprano |
| Score de fraude alto | HITL activado |

---

## 14. Flujo de trabajo del equipo

### Ramas Git

```
main          ← rama estable, solo merge con PR aprobado
develop       ← rama de integración continua
feature/XXX   ← una rama por tarea (ver planificación)
```

### Convención de commits

```
feat(agent-b): implementar validación documental
fix(rag): corregir chunking de PDFs escaneados
docs(readme): añadir sección de testing
test(e2e): añadir caso de fraude OFAC
```

### Distribución de responsabilidades

| Rol | Responsable | Tareas principales |
|---|---|---|
| Dev1 — LangGraph | — | Agentes A, C, E · Schema MariaDB |
| Dev2 — APIs & Tools | — | Agentes B, G · Mock APIs |
| RAG — Data Eng. | — | Dataset sintético · ChromaDB · Agente D |
| Frontend — UI | — | Streamlit app · Dashboard CoT |
| Doc — Técnico | — | Memoria E2 · Catálogo herramientas · Manual |
| Lead — QA | — | Integración E2E · Demo · Coordinación |

### Hitos de la Entrega 2

| Fecha | Hito |
|---|---|
| 25 mayo | Punto de control: infraestructura operativa + Agente A funcionando |
| 15 junio | Code freeze: todos los agentes implementados |
| 22 junio | Demo grabada (vídeo ≤ 4 min) |
| 26 junio 23:59 CET | **Entrega 2 en plataforma OBS** |

---

## 15. Variables de entorno

Referencia completa del fichero `.env`:

```bash
# ── LLM ──────────────────────────────────────────────────────
ANTHROPIC_API_KEY=              # Clave API de Anthropic (obligatoria)

# ── MariaDB ──────────────────────────────────────────────────
DB_ROOT_PASSWORD=root_dev       # Contraseña root (solo dev)
DB_NAME=smart_claims            # Nombre de la base de datos
DB_USER=claims_user             # Usuario de la aplicación
DB_PASSWORD=claims_dev          # Contraseña del usuario
DB_HOST=mariadb                 # Nombre del servicio Docker
DB_PORT=3306

# ── ChromaDB ─────────────────────────────────────────────────
CHROMA_HOST=chromadb            # Nombre del servicio Docker
CHROMA_PORT=8000
CHROMA_COLLECTION=pepin_policies

# ── Backend ──────────────────────────────────────────────────
BACKEND_URL=http://backend:8000

# ── Lógica de negocio ────────────────────────────────────────
HITL_AMOUNT_THRESHOLD=5000.0    # Importe (€) que activa revisión humana

# ── General ──────────────────────────────────────────────────
ENVIRONMENT=development
LOG_LEVEL=INFO
```

---

## 16. Decisiones de diseño

| Decisión | Alternativas consideradas | Motivo |
|---|---|---|
| LangGraph sobre LangChain LCEL | LangChain LCEL · Autogen | Gestión de estado por expediente y HITL nativo |
| ChromaDB local | Pinecone · Weaviate | Sin coste, reproducible, sin dependencias cloud |
| MariaDB sobre SQLite | SQLite · PostgreSQL | Más cercana a producción, soporte DECIMAL para importes |
| Mock APIs sobre integraciones reales | — | Reproducibilidad en entorno académico, sin datos reales |
| Claude Sonnet sobre GPT-4o | GPT-4o · Mistral | Mejor rendimiento en español, API tool use más estable |
| HITL por umbral de importe | HITL por confianza del modelo | Criterio auditable y comprensible por el negocio |

---

## 17. Registro de cambios

### v0.2.0 — Entrega 2 *(en curso)*
- Infraestructura Docker completa (5 servicios)
- Agente A — Orquestador LangGraph ReAct implementado
- Mock APIs completas (8 tools)
- Schema MariaDB con 3 tablas y seed de demo
- Dataset sintético *(pendiente)*
- Agentes B, C, D, E, G *(pendiente)*
- Frontend Streamlit *(pendiente)*

### v0.1.0 — Entrega 1 *(entregada 08/05/2026)*
- Diagnóstico AS-IS del proceso de Seguros Pepín
- Diseño conceptual de la arquitectura agéntica
- Catálogo de agentes A–H con trazabilidad a pain points
- Stack tecnológico definido
- Roadmap del TFM
