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
import os

import requests

# Globals
_LLM_API_BASE = os.environ.get("LLM_API_BASE", "http://localhost:11434/v1")
_LLM_EMBED_MODEL = os.environ.get("LLM_EMBED_MODEL", "nomic-embed-text")
_LLM_GEN_MODEL = os.environ.get("LLM_GEN_MODEL", "llama3")

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
            return None
        return data["data"][0]["embedding"]
    except Exception:
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
            return None
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None


if __name__ == "__main__":
    pass
