"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    LLM API client. Two roles:
      1. Embedding model (e.g. nomic-embed-text) — called during indexing
         and deferred vectorization.
      2. Generative model (e.g. llama3, mistral) — called at query time
         for AI summary generation (RAG).
    Uses a single OpenAI-compatible HTTP endpoint (LLM_API_BASE).
    Falls back gracefully when the LLM API is unreachable.
"""
# Imports
import logging
import os
import threading

import requests

# Globals
logger = logging.getLogger(__name__)
_LLM_API_BASE = os.environ.get("LLM_API_BASE", "http://localhost:11434/v1")
_LLM_EMBED_MODEL = os.environ.get("LLM_EMBED_MODEL", "nomic-embed-text")
_LLM_GEN_MODEL = os.environ.get("LLM_GEN_MODEL", "granite4.1:8b")
_LLM_REWRITE_MODEL = os.environ.get("LLM_REWRITE_MODEL", "granite4.1:3b")
_CPU_EMBED_MODEL = "nomic-ai/nomic-embed-text-v1"

_TIMEOUT = 30
_cpu_model = None
_cpu_model_lock = threading.Lock()

_DEFAULT_SUMMARY_TEMPLATE = (
    "You are a search assistant for a private homelab index. Answer using "
    "ONLY the context provided. Rules: (1) no outside knowledge, "
    "(2) 2–4 sentences max, (3) if the answer is not in the context respond "
    'with exactly "The index doesn\'t contain information about that.", '
    "(4) do not speculate or mention you are an AI.\n\n"
    "Context:\n{context}\n\nQuestion: {query}\nAnswer:"
)


# Functions
def _get_llm_settings(db_session=None):
    """
    Input:  db_session — optional SQLAlchemy session (injectable for tests)
    Output: dict with gen_model, embed_model, summary_template
    Details:
        Reads from system_settings table; falls back to env-var values when
        the DB is unreachable or the key is absent.  Called at query time so
        admin changes take effect on the next request without a restart.
    """
    try:
        from flask_app import db
        from flask_app.models.system_setting import SystemSetting
        session = db_session or db.session

        def _get(k):
            row = session.get(SystemSetting, k)
            return row.value if row else None

        return {
            "gen_model":        _get("llm.gen_model")        or _LLM_GEN_MODEL,
            "embed_model":      _get("llm.embed_model")      or _LLM_EMBED_MODEL,
            "summary_template": _get("llm.summary_template") or _DEFAULT_SUMMARY_TEMPLATE,
        }
    except Exception:
        logger.warning("_get_llm_settings: DB read failed, using env-var defaults", exc_info=True)
        return {
            "gen_model":        _LLM_GEN_MODEL,
            "embed_model":      _LLM_EMBED_MODEL,
            "summary_template": _DEFAULT_SUMMARY_TEMPLATE,
        }


def get_embedding(text, session=None):
    """
    Input:
        text    - str, the text to embed
        session - optional requests.Session for injection in tests
    Output:
        list[float] embedding vector, or None if the LLM API is unreachable
    Details:
        POSTs to {LLM_API_BASE}/embeddings using the model in LLM_EMBED_MODEL.
        Returns None (no exception) when the endpoint is unreachable or returns
        an error so that callers can proceed with vectorized=false.
    """
    requester = session or requests
    url = f"{_LLM_API_BASE}/embeddings"
    payload = {"model": _LLM_EMBED_MODEL, "input": text}
    try:
        resp = requester.post(url, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            logger.warning("LLM embedding API returned error: %s", data.get("error"))
            return None
        return data["data"][0]["embedding"]
    except Exception:
        logger.warning("get_embedding failed", exc_info=True)
        return None


def get_cpu_embedding(text):
    """
    Input:  text — str, the text to embed
    Output: list[float] embedding vector, or None on any failure
    Details:
        CPU-based fallback for get_embedding() when the LLM API is unreachable.
        Lazy-loads nomic-ai/nomic-embed-text-v1 via sentence-transformers on first
        call (one-time download ~274 MB; cached in ~/.cache/huggingface/hub).
        Produces 768-dimensional embeddings compatible with the stored index vectors
        so vector_search() results remain semantically correct.
        Thread-safe: uses a double-checked lock so only one thread loads the model.
    """
    global _cpu_model
    if _cpu_model is None:
        with _cpu_model_lock:
            if _cpu_model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                    _cpu_model = SentenceTransformer(
                        _CPU_EMBED_MODEL, trust_remote_code=True
                    )
                except Exception:
                    logger.warning(
                        "get_cpu_embedding: failed to load %s", _CPU_EMBED_MODEL, exc_info=True
                    )
                    return None
    try:
        return _cpu_model.encode(text).tolist()
    except Exception:
        logger.warning("get_cpu_embedding: encode failed", exc_info=True)
        return None


def generate_summary(context_chunks, query, session=None, db_session=None):
    """
    Input:
        context_chunks - list[str], document chunks retrieved by vector search
        query          - str, the user's original search query
        session        - optional requests.Session for injection in tests
        db_session     - optional SQLAlchemy session for _get_llm_settings injection
    Output:
        str summary, or None if the LLM API is unreachable
    Details:
        Reads gen_model and summary_template from system_settings (via
        _get_llm_settings) with env-var fallback.  Formats the template with
        {context} and {query} substitution and sends a single user message.
        Returns None (no exception) when the endpoint is unreachable.
    """
    settings = _get_llm_settings(db_session=db_session)
    requester = session or requests
    url = f"{_LLM_API_BASE}/chat/completions"
    context = "\n\n".join(context_chunks)
    prompt = settings["summary_template"].format(context=context, query=query)
    messages = [{"role": "user", "content": prompt}]
    payload = {"model": settings["gen_model"], "messages": messages}
    try:
        resp = requester.post(url, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            logger.warning("LLM generate_summary API returned error: %s", data.get("error"))
            return None
        return data["choices"][0]["message"]["content"]
    except Exception:
        logger.warning("generate_summary failed", exc_info=True)
        return None


def rewrite_query(raw_query, session=None):
    """
    Input:
        raw_query - str, the user's raw natural-language query
        session   - optional requests.Session for injection in tests
    Output:
        str — rewritten terse search query, or raw_query unchanged on any failure
    Details:
        POSTs to {LLM_API_BASE}/chat/completions using LLM_REWRITE_MODEL.
        The system prompt instructs the model to strip conversational preamble
        and return only a concise 2-6 word search query. Always returns a
        usable string: falls back to raw_query on connection error, HTTP error,
        empty response, or any other exception so callers are never blocked.
    """
    requester = session or requests
    url = f"{_LLM_API_BASE}/chat/completions"
    messages = [
        {
            "role": "system",
            "content": (
                "You are a search query optimizer. Rewrite the user's input as a "
                "concise search query of 2-6 words. Remove conversational preamble, "
                "filler, and politeness. Preserve the core intent. Return ONLY the "
                "rewritten query — no explanation, no leading/trailing punctuation."
            ),
        },
        {"role": "user", "content": raw_query},
    ]
    payload = {"model": _LLM_REWRITE_MODEL, "messages": messages}
    try:
        resp = requester.post(url, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            logger.warning("LLM rewrite_query API returned error: %s", data.get("error"))
            return raw_query
        rewritten = data["choices"][0]["message"]["content"].strip()
        if not rewritten:
            return raw_query
        return rewritten
    except Exception:
        logger.warning("rewrite_query failed", exc_info=True)
        return raw_query


def generate_keywords(query, context_chunks, session=None):
    """
    Input:
        query          - str, the user's original search query
        context_chunks - list[str], document text from vector search results
        session        - optional requests.Session for injection in tests
    Output:
        list[str] of 4-6 related search terms, or [] if the LLM API is unreachable
    Details:
        Asks the generative model to suggest related search queries the user
        could try to explore the topic further. Returns plain terms only —
        no bullets, numbers, or explanation. Empty lines and duplicates are
        removed. Falls back to [] without raising.
    """
    requester = session or requests
    url = f"{_LLM_API_BASE}/chat/completions"
    context = "\n\n".join(context_chunks[:3]) if context_chunks else ""
    messages = [
        {
            "role": "system",
            "content": (
                "You are a search assistant. Your only job is to suggest related "
                "search terms. Return ONLY the terms themselves — no numbers, "
                "no bullets, no explanation. One term per line. 2-4 words each. "
                "Maximum 6 terms."
            ),
        },
        {
            "role": "user",
            "content": (
                f'The user searched for: "{query}"\n\n'
                f"Context from results:\n{context}\n\n"
                "Suggest 5 related search terms:"
            ),
        },
    ]
    payload = {"model": _LLM_REWRITE_MODEL, "messages": messages}
    try:
        resp = requester.post(url, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            logger.warning("LLM generate_keywords API returned error: %s", data.get("error"))
            return []
        raw = data["choices"][0]["message"]["content"]
        seen = set()
        chips = []
        for line in raw.splitlines():
            term = line.strip().lstrip("-•*0123456789.) ")
            if term and term.lower() != query.lower() and term not in seen:
                seen.add(term)
                chips.append(term)
            if len(chips) >= 6:
                break
        return chips
    except Exception:
        logger.warning("generate_keywords failed", exc_info=True)
        return []


if __name__ == "__main__":
    pass
