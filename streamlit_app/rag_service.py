"""RAG service — embeds project reference docs and retrieves relevant chunks."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).resolve().parent / ".rag_cache.json"
_DATA_ROOT = Path(__file__).resolve().parents[1] / "Data"
_README_PATH = Path(__file__).resolve().parents[1] / "README.md"
_EMBED_MODEL = "gemini-embedding-001"
_CHUNK_MAX = 400

# Module-level state, populated lazily
_chunks: list[dict[str, Any]] = []
_embeddings: list[list[float]] = []
_initialized = False


def is_rag_configured() -> bool:
    """Return True when GEMINI_API_KEY is available."""
    from config_utils import get_secret
    return bool(get_secret("GEMINI_API_KEY"))


def retrieve(query: str, top_k: int = 4) -> list[dict[str, Any]]:
    """Embed query and return top_k chunks sorted by cosine similarity descending."""
    _ensure_initialized()
    if not _chunks or not _embeddings:
        return []

    try:
        import numpy as np

        q_emb = np.array(_embed_single(query, task_type="RETRIEVAL_QUERY"), dtype=float)
        chunk_embs = np.array(_embeddings, dtype=float)

        norms = np.linalg.norm(chunk_embs, axis=1) * np.linalg.norm(q_emb)
        scores = (chunk_embs @ q_emb) / np.clip(norms, 1e-10, None)
        top_indices = np.argsort(scores)[::-1][:top_k]

        return [
            {
                "text": _chunks[i]["text"],
                "source": _chunks[i]["source"],
                "score": float(scores[i]),
            }
            for i in top_indices
        ]
    except Exception as exc:
        logger.warning("RAG retrieve failed: %s: %s", type(exc).__name__, exc)
        return []


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _ensure_initialized() -> None:
    global _initialized, _chunks, _embeddings
    if _initialized:
        return
    _initialized = True

    try:
        raw_chunks = _build_chunks()
        if not raw_chunks:
            return

        content_hash = _hash_sources()
        cached = _load_cache()

        if cached and cached.get("content_hash") == content_hash:
            items = cached.get("items", [])
            _chunks = [{"text": it["text"], "source": it["source"]} for it in items]
            _embeddings = [it["embedding"] for it in items]
            return

        if not is_rag_configured():
            _chunks = raw_chunks
            return

        embeddings = _embed_all_chunks(raw_chunks)
        if not embeddings:
            _chunks = raw_chunks
            return

        _chunks = raw_chunks
        _embeddings = embeddings
        _save_cache(content_hash, raw_chunks, embeddings)

    except Exception as exc:
        logger.warning("RAG initialization failed: %s: %s", type(exc).__name__, exc)


def _build_chunks() -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []

    # --- map_cities.json ---
    try:
        cities = _read_json(_DATA_ROOT / "map_cities.json")
        for city in cities:
            name = city.get("city") or ""
            state = city.get("state") or ""
            region = city.get("region") or ""
            if name:
                text = (
                    f"City: {name} | State: {state} | Region: {region} | Country: US. "
                    f"{name} is a US city located in the {region} region, state {state}."
                )
                chunks.append({"text": text, "source": "map_cities.json"})
    except Exception as exc:
        logger.warning("Failed to load map_cities.json: %s", exc)

    # --- map_cancellation_reasons.json ---
    try:
        reasons = _read_json(_DATA_ROOT / "map_cancellation_reasons.json")
        for reason in reasons:
            label = reason.get("cancellation_reason")
            if label:
                text = (
                    f"Cancellation reason: {label}. "
                    f"This is one of the ride cancellation codes used in the Uber platform."
                )
                chunks.append({"text": text, "source": "map_cancellation_reasons.json"})
    except Exception as exc:
        logger.warning("Failed to load map_cancellation_reasons.json: %s", exc)

    # --- map_vehicle_types.json ---
    try:
        vehicles = _read_json(_DATA_ROOT / "map_vehicle_types.json")
        for v in vehicles:
            vtype = v.get("vehicle_type") or ""
            desc = v.get("description") or ""
            base = v.get("base_rate", "")
            per_mile = v.get("per_mile", "")
            per_min = v.get("per_minute", "")
            if vtype:
                text = (
                    f"Vehicle type: {vtype}. Description: {desc}. "
                    f"Base rate: ${base}, per mile: ${per_mile}, per minute: ${per_min}. "
                    f"{vtype} is a service tier available in the Uber platform."
                )
                chunks.append({"text": text, "source": "map_vehicle_types.json"})
    except Exception as exc:
        logger.warning("Failed to load map_vehicle_types.json: %s", exc)

    # --- README.md ---
    try:
        readme_text = _README_PATH.read_text(encoding="utf-8")
        for chunk_text in _chunk_text(readme_text, max_size=_CHUNK_MAX):
            chunks.append({"text": chunk_text, "source": "README.md"})
    except Exception as exc:
        logger.warning("Failed to load README.md: %s", exc)

    return chunks


def _chunk_text(text: str, max_size: int = 400) -> list[str]:
    """Split text on paragraph boundaries without splitting mid-sentence."""
    paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if not current:
            current = para
        elif len(current) + len(para) + 2 <= max_size:
            current = current + "\n\n" + para
        else:
            chunks.append(current)
            current = para
    if current:
        chunks.append(current)
    return chunks


def _embed_all_chunks(chunks: list[dict[str, Any]]) -> list[list[float]]:
    """Embed all chunk texts; return list of embedding vectors."""
    embeddings: list[list[float]] = []
    for chunk in chunks:
        try:
            emb = _embed_single(chunk["text"], task_type="RETRIEVAL_DOCUMENT")
            embeddings.append(emb)
        except Exception as exc:
            logger.warning("Embedding failed for chunk '%s...': %s", chunk["text"][:40], exc)
            embeddings.append([])
    return embeddings


def _embed_single(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    """Embed a single text using Gemini text-embedding-004."""
    from config_utils import get_secret
    from google import genai
    from google.genai import types

    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)
    response = client.models.embed_content(
        model=_EMBED_MODEL,
        contents=text,
        config=types.EmbedContentConfig(task_type=task_type),
    )
    return list(response.embeddings[0].values)


def _hash_sources() -> str:
    """SHA-256 of all source file contents combined."""
    h = hashlib.sha256()
    for path in [
        _DATA_ROOT / "map_cities.json",
        _DATA_ROOT / "map_cancellation_reasons.json",
        _DATA_ROOT / "map_vehicle_types.json",
        _README_PATH,
    ]:
        try:
            h.update(path.read_bytes())
        except OSError:
            pass
    return h.hexdigest()


def _load_cache() -> dict[str, Any] | None:
    try:
        if _CACHE_PATH.exists():
            return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load RAG cache: %s", exc)
    return None


def _save_cache(
    content_hash: str,
    chunks: list[dict[str, Any]],
    embeddings: list[list[float]],
) -> None:
    try:
        items = [
            {"text": c["text"], "source": c["source"], "embedding": emb}
            for c, emb in zip(chunks, embeddings)
        ]
        _CACHE_PATH.write_text(
            json.dumps({"content_hash": content_hash, "items": items}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Failed to save RAG cache: %s", exc)


def _read_json(path: Path) -> list[Any]:
    return json.loads(path.read_text(encoding="utf-8"))
