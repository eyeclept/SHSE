# AI Query Rewriter

The query rewriter is an optional pre-search step that sends the user's raw
natural-language input to a small instruction-tuned model and receives a terse,
operator-friendly search query in return. It runs *before* the preprocessing
pipeline result reaches OpenSearch and is entirely transparent when disabled.

---

## What it does

A user may type "please tell me how to configure a reverse proxy" into the
search box. BM25 and the preprocessing pipeline can partially improve this, but
a 12-word conversational sentence is still a weaker query than "reverse proxy
config". The rewriter calls a 3B-parameter model with a strict system prompt and
replaces the verbose input with the concise equivalent before the search backend
is called.

The rewriter only runs when:
1. `QUERY_REWRITE_ENABLED=true` is set in the environment.
2. The model returns a non-empty string that differs from the preprocessed query.

If either condition fails, the preprocessed query is used as-is. The search
result is therefore never blocked by the rewriter.

---

## How to enable

Set the environment variable in `.env` (or Docker Compose environment block):

```
QUERY_REWRITE_ENABLED=true
```

The feature is disabled by default (`false`). No restart of the index or
database is required — only the Flask and Celery worker containers need to be
restarted to pick up the new value.

---

## Model selection

Two env vars control which Ollama models are used:

| Variable | Default | Purpose |
|---|---|---|
| `LLM_REWRITE_MODEL` | `granite4.1:3b` | Query rewriter (fast, small) |
| `LLM_GEN_MODEL` | `granite4.1:8b` | AI summary / keyword generation |
| `LLM_EMBED_MODEL` | `nomic-embed-text` | Embedding for vector search |
| `LLM_API_BASE` | `http://localhost:11434/v1` | OpenAI-compatible base URL |

The rewriter intentionally uses a smaller model than the summary model. The
task (strip preamble, return 2-6 words) does not require a large context window
or complex reasoning, and a 3B model reduces added latency to ~100-300 ms on
typical homelab hardware.

To use a different model for rewriting:

```
LLM_REWRITE_MODEL=granite4.1:1b
```

To disable only the rewriter while keeping AI summaries:

```
QUERY_REWRITE_ENABLED=false
LLM_GEN_MODEL=granite4.1:8b
```

---

## Interaction with the preprocessing pipeline (Epic 23)

The preprocessing pipeline and the query rewriter are independent and
complementary:

```
raw query
  → strip_preamble()
  → normalize()
  → strip_stopwords()
  → expand_synonyms()
  → preprocessed_q          ← shown as "Searching for: …" annotation
  → rewrite_query()          ← only when QUERY_REWRITE_ENABLED=true
  → rewritten_q              ← shown as "AI rewrote query to: …" annotation
  → OpenSearch BM25 + kNN
```

The rewriter receives `preprocessed_q` (the output of the pipeline), not the
raw input. This means stopwords are already removed and synonyms already
expanded before the model sees the query. Both annotations are shown in the
results UI when they differ from the raw input, so users can see exactly what
was searched.

---

## Performance considerations

Each search request with `QUERY_REWRITE_ENABLED=true` makes one additional
POST to the LLM API before the OpenSearch call. Expected overhead per search:

| Hardware | `granite4.1:3b` latency (estimated) |
|---|---|
| CPU-only (8-core) | 2–6 s |
| GPU (RTX 3060 12 GB) | 100–400 ms |
| GPU (RTX 4090) | 50–150 ms |

The rewriter uses a 30-second timeout (shared with other LLM calls). If the
model is slow or unavailable, the fallback to `preprocessed_q` fires
immediately on timeout expiry — the user always receives search results.

For CPU-only deployments where latency is unacceptable, leave
`QUERY_REWRITE_ENABLED=false` and rely on the preprocessing pipeline alone.

---

## How to disable per-operator

The flag is a single env var; there is no per-user or per-request toggle. To
disable for all users, set `QUERY_REWRITE_ENABLED=false` and restart Flask.

For temporary testing without a restart, the `Config.QUERY_REWRITE_ENABLED`
class attribute can be overridden in `flask shell`:

```python
from flask_app.config import Config
Config.QUERY_REWRITE_ENABLED = False
```

This change is process-scoped and lost on restart.
