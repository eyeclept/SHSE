# Offline Translation Answer Cards

Inline answer cards for translation queries. Text is translated entirely offline
via the local Ollama instance — no cloud API. The card appears above BM25 results
when a translation trigger phrase is detected. A 15-second timeout is enforced;
if Ollama is unreachable or the model exceeds the timeout the card is silently
skipped and search results render normally.

---

## Supported Query Patterns

| Pattern | Example |
|---|---|
| `translate <text> to <lang>` | `translate hello to Spanish` |
| `how do you say <text> in <lang>` | `how do you say goodbye in French` |
| `what is <text> in <lang>` | `what is dog in Japanese` |

Plain queries with no trigger word (e.g. `hello`, `define hello`) always return
`None` and no card is shown.

---

## Model Recommendation

| Model | Size | Languages | Notes |
|---|---|---|---|
| `aya-expanse:8b` (**default**) | ~5 GB | 101 languages | Purpose-built for multilingual tasks (Cohere) |
| `qwen2.5:3b` | ~2 GB | Excellent CJK + European | Lower RAM requirement |

Pull the model before use:
```bash
ollama pull aya-expanse:8b
# or for the lighter alternative:
ollama pull qwen2.5:3b
```

---

## Ollama Setup

The translation service calls the OpenAI-compatible `/chat/completions` endpoint
at `LLM_API_BASE`. This is the same base URL used by other LLM features.

```env
LLM_API_BASE=http://localhost:11434/v1
LLM_TRANSLATE_MODEL=aya-expanse:8b
```

To use a different model (without restarting the stack):

```env
LLM_TRANSLATE_MODEL=qwen2.5:3b
```

---

## `LLM_TRANSLATE_MODEL` Config

The model is configured independently of the generation and rewrite models so
admins can tune translation without affecting AI summaries or query rewriting.

| Env var | Default | Description |
|---|---|---|
| `LLM_TRANSLATE_MODEL` | `aya-expanse:8b` | Model used for translation cards |
| `LLM_API_BASE` | `http://localhost:11434/v1` | Shared base URL for all LLM calls |

---

## Timeout Behaviour

A 15-second timeout is enforced per translation request. If the model is slow
or Ollama is unreachable:

- `translate_text` returns `None` and logs a `WARNING`
- `build_translate_card` returns `(None, None)`
- BM25 results render normally; no error is shown to the user

---

## `ai_context` Injection

When a translation card is shown, the result is prepended to `ai_context` as:

```
Translation of 'hello' in Spanish: Hola
```

---

## Known Limitations

- No automatic source language detection: the model is prompted to infer the
  source language. This works well with multilingual models like `aya-expanse`
  but may fail for very short or ambiguous input.
- Translation quality depends entirely on the model and its training data.
- The card is synchronous — there is no HTMX-deferred loading. The full
  translation latency adds to page load time.
