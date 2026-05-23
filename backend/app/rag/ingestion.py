"""
RAG ingestion pipeline — loads policy Markdown files into ChromaDB.

Collection: smart_claims_policies
Embeddings: sentence-transformers all-MiniLM-L6-v2 (local, no API key needed)

Usage (inside Docker or local venv):
    python -m app.rag.ingestion
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)

COLLECTION_NAME = "smart_claims_policies"
_DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).parent.parent.parent.parent / "data")))
POLICIES_DIR = _DATA_DIR / "policies"
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "chromadb")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8000"))
EMBED_MODEL = "all-MiniLM-L6-v2"
CHUNK_SIZE = 600   # characters
CHUNK_OVERLAP = 100


def _chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks by character count."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end].strip())
        start += size - overlap
    return [c for c in chunks if c]


def _doc_id(file_stem: str, chunk_idx: int) -> str:
    raw = f"{file_stem}::{chunk_idx}"
    return hashlib.md5(raw.encode()).hexdigest()


def _get_client():
    """HTTP server first, then embedded persistent client."""
    try:
        client = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)
        client.heartbeat()
        return client
    except Exception:
        persist_dir = _DATA_DIR / "chroma"
        persist_dir.mkdir(parents=True, exist_ok=True)
        return chromadb.PersistentClient(path=str(persist_dir))


def _get_embed_fn() -> embedding_functions.SentenceTransformerEmbeddingFunction:
    return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)


async def ingest_policies(policies_dir: Path | None = None) -> int:
    """
    Load all .md files from policies_dir into ChromaDB.

    Returns the total number of chunks ingested.
    Idempotent: existing documents with the same ID are overwritten.
    """
    source_dir = policies_dir or POLICIES_DIR
    md_files = list(source_dir.glob("*.md"))
    if not md_files:
        logger.warning("No .md policy files found in %s", source_dir)
        return 0

    client = _get_client()
    embed_fn = _get_embed_fn()
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )

    total = 0
    for md_file in md_files:
        text = md_file.read_text(encoding="utf-8")
        chunks = _chunk_text(text)
        ids = [_doc_id(md_file.stem, i) for i in range(len(chunks))]
        metadatas = [
            {"source": md_file.name, "chunk": i, "stem": md_file.stem}
            for i in range(len(chunks))
        ]
        collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)
        logger.info("Ingested %s: %d chunks", md_file.name, len(chunks))
        total += len(chunks)

    logger.info("Ingestion complete — %d total chunks in collection '%s'", total, COLLECTION_NAME)
    return total


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(ingest_policies())
