"""
Smart-Claims Agent — Backend entrypoint.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import logging

from app.db.session import init_db
from app.rag.ingestion import ingest_policies
from app.routers import claims, agents, health

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    try:
        n = await ingest_policies()
        logger.info("RAG: %d policy chunks ingested into ChromaDB", n)
    except Exception as exc:
        logger.warning("RAG ingestion skipped (ChromaDB not ready?): %s", exc)
    yield


app = FastAPI(
    title="Smart-Claims Agent",
    description="MVP d'agent agèntic per a la gestió de sinistres — Seguros Pepín",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],  # Streamlit
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
app.include_router(claims.router, prefix="/api/v1/claims", tags=["claims"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["agents"])
