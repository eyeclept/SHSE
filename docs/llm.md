# LLM API Integration

SHSE uses a single OpenAI-compatible HTTP endpoint for both embedding and generative tasks.
In the lab stack this is typically LiteLLM proxying to Triton or Ollama,
but any OpenAI-compatible server works.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LLM_API_BASE` | `http://localhost:11434/v1` | Base URL of the OpenAI-compatible endpoint |
| `LLM_EMBED_MODEL` | `nomic-embed-text` | Model name used for embedding calls |
| `LLM_GEN_MODEL` | `llama3` | Model name used for generative summary calls |

All three variables are read at import time from the environment.
Set them in `.env` before starting the stack.

---

## Embedding Model

**Function:** `get_embedding(text, session=None)` in `flask_app/services/llm.py`

**Endpoint:** `POST {LLM_API_BASE}/embeddings`

**Request body:**
```json
{
  "model": "<LLM_EMBED_MODEL>",
  "input": "<text>"
}
```

**Response (success):**
```json
{
  "data": [
    { "embedding": [0.012, -0.034, ...] }
  ]
}
```

**Returns:** `list[float]` — the embedding vector, or `None` if the API is unreachable
or returns an error field.

Callers (the Celery vectorize task) must check for `None` and store
`vectorized=false` + `embedding=null` when `None` is returned.

---

## Generative Model (RAG)

**Function:** `generate_summary(context_chunks, query, session=None)` in `flask_app/services/llm.py`

**Endpoint:** `POST {LLM_API_BASE}/chat/completions`

**Prompt structure:** A system message instructing the model to answer using only
provided context, followed by a user message concatenating the context chunks and
the search query.

**Request body:**
```json
{
  "model": "<LLM_GEN_MODEL>",
  "messages": [
    { "role": "system", "content": "..." },
    { "role": "user",   "content": "Context:\n<chunks>\n\nQuestion: <query>" }
  ]
}
```

**Response (success):**
```json
{
  "choices": [
    { "message": { "content": "Summary text..." } }
  ]
}
```

**Returns:** `str` summary, or `None` if the API is unreachable or returns an error field.

---

## RAG Flow

1. User submits a search query.
2. Search route calls `get_embedding(query)`.
   - If `None` → fall back to BM25-only; skip AI summary card.
3. `vector_search(query_embedding)` retrieves top-k document chunks.
4. `generate_summary(chunks, query)` generates an AI summary.
   - If `None` → AI summary card is hidden.
5. Both BM25 results and (optionally) the AI summary are rendered.

---

## Fallback Behavior

Both `get_embedding` and `generate_summary` catch all exceptions internally and
return `None`. No exception propagates to the caller. This ensures:

- Indexing continues with `vectorized=false` when the embedding model is down.
- Search continues with BM25 results when the generative model is down.
- The admin health-check route is the correct place to surface LLM API status to operators.
