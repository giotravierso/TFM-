"""
Shared ChromaDB retriever for Agents D (coverage) and H (conversational).

Connection priority:
  1. HTTP server  (CHROMADB_HOST:CHROMADB_PORT — Docker/cloud)
  2. Embedded persistent client  (DATA_DIR/chroma/ — local dev, no server needed)
  3. None  (agents use hardcoded fallback rules)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

try:
    import chromadb
    from chromadb.utils import embedding_functions
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False

logger = logging.getLogger(__name__)

COLLECTION_NAME = "smart_claims_policies"
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "chromadb")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8000"))
EMBED_MODEL = "all-MiniLM-L6-v2"
DEFAULT_N_RESULTS = 5
_DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).parent.parent.parent.parent / "data")))
CHROMA_PERSIST_DIR = _DATA_DIR / "chroma"


class _ChromaRetriever:
    """Thin synchronous wrapper around a ChromaDB collection."""

    def __init__(self, collection) -> None:
        self._col = collection

    def query(self, text: str, n_results: int = DEFAULT_N_RESULTS) -> list[dict]:
        """Return top-n chunks relevant to `text`."""
        try:
            count = self._col.count()
            if count == 0:
                return []
            n = min(n_results, count)
        except Exception:
            n = n_results

        results = self._col.query(
            query_texts=[text],
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )
        items: list[dict] = []
        if not results["documents"]:
            return items
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            items.append({
                "document": doc,
                "source": meta.get("source", ""),
                "chunk": meta.get("chunk", 0),
                "distance": round(dist, 4),
            })
        return items


_retriever_cache: _ChromaRetriever | None = None


def _make_embed_fn():
    return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)


def _get_collection(client):
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=_make_embed_fn(),
        metadata={"hnsw:space": "cosine"},
    )


def reset_retriever_cache() -> None:
    """Force re-initialisation on next call (e.g. after new docs are ingested)."""
    global _retriever_cache
    _retriever_cache = None


async def get_coverage_retriever() -> _ChromaRetriever:
    """Return (and cache) the shared policy retriever.

    Tries HTTP server first, then embedded persistent client, then None.
    """
    global _retriever_cache
    if _retriever_cache is not None:
        return _retriever_cache

    if not _CHROMA_AVAILABLE:
        logger.warning("chromadb not installed — agents will use fallback rules")
        return None  # type: ignore[return-value]

    # 1. Try HTTP server (Docker / cloud)
    try:
        client = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)
        client.heartbeat()
        collection = _get_collection(client)
        _retriever_cache = _ChromaRetriever(collection)
        logger.info("ChromaDB HTTP retriever ready (collection: %s)", COLLECTION_NAME)
        return _retriever_cache
    except Exception:
        pass

    # 2. Embedded persistent client (local dev — no server needed)
    try:
        CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
        collection = _get_collection(client)
        _retriever_cache = _ChromaRetriever(collection)
        logger.info("ChromaDB embedded retriever ready (path: %s, docs: %d)",
                    CHROMA_PERSIST_DIR, collection.count())
        return _retriever_cache
    except Exception as exc:
        logger.warning("ChromaDB embedded failed (%s) — agents will use fallback rules", exc)
        return None  # type: ignore[return-value]
