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

import requests

# Globals
logger = logging.getLogger(__name__)
_LLM_API_BASE = os.environ.get("LLM_API_BASE", "http://localhost:11434/v1")
_LLM_EMBED_MODEL = os.environ.get("LLM_EMBED_MODEL", "nomic-embed-text")
_LLM_GEN_MODEL = os.environ.get("LLM_GEN_MODEL", "granite4.1:8b")
_LLM_REWRITE_MODEL = os.environ.get("LLM_REWRITE_MODEL", "granite4.1:3b")

_TIMEOUT = 30


# Functions
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


def generate_summary(context_chunks, query, session=None):
    """
    Input:
        context_chunks - list[str], document chunks retrieved by vector search
        query          - str, the user's original search query
        session        - optional requests.Session for injection in tests
    Output:
        str summary, or None if the LLM API is unreachable
    Details:
        Builds a RAG prompt from context_chunks and query, then POSTs to
        {LLM_API_BASE}/chat/completions using the model in LLM_GEN_MODEL.
        Returns None (no exception) when the endpoint is unreachable.
    """
    requester = session or requests
    url = f"{_LLM_API_BASE}/chat/completions"
    context = "\n\n".join(context_chunks)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a search assistant for a private homelab. "
                "Answer using only the context provided. "
                "If the context does not contain the answer, say so."
            ),
        },
        {
            "role": "user",
            "content": f"Context:\n{context}\n\nQuestion: {query}",
        },
    ]
    payload = {"model": _LLM_GEN_MODEL, "messages": messages}
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
