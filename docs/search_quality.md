# Search Quality

SHSE applies a multi-stage pipeline to every query before it reaches OpenSearch. This document describes each stage, the synonym configuration, the hybrid search algorithm, and fallback behaviour.

---

## 1. Preprocessing Pipeline

Source: `flask_app/services/query_preprocessor.py`

Every query passes through four stages in order:

```
strip_preamble → normalize → strip_stopwords → expand_synonyms
```

### strip_preamble

Removes leading natural-language filler phrases that contribute no search signal.

| Input | Output |
|---|---|
| `please search for server config` | `server config` |
| `what is Docker` | `Docker` |
| `how do I configure nginx` | `configure nginx` |
| `server config` | `server config` (unchanged) |

Patterns matched (case-insensitive, anchored at the start):
- `please search for`, `find me`, `search for`, `look up`
- `what is / are`, `who is / are`
- `tell me about / how / what ...`
- `show me`, `give me`, `how do I`, `how to`
- `can you find / search for / look up`
- `help me find / understand / with`

If stripping the preamble would leave an empty string the original input is returned unchanged.

### normalize

Lowercases the entire string, removes characters that are neither alphanumeric, space, hyphen, nor apostrophe, and collapses runs of whitespace to a single space.

| Input | Output |
|---|---|
| `NGINX Config` | `nginx config` |
| `  Hello,  World!  ` | `hello world` |
| `it's a self-signed cert` | `it's a self-signed cert` |

### strip_stopwords

Removes tokens present in the `STOPWORDS` set (common English function words: `the`, `a`, `is`, `for`, `in`, `of`, etc.). If removing stopwords would leave an empty string the normalized form is returned unchanged.

### expand_synonyms

Appends synonym terms for each token found in `config/synonyms.yaml`. Synonyms are appended after the original query so the original terms remain in the OpenSearch query with their natural weight.

```
Input:  server config
Output: server config host machine node
```

The injected `synonym_map` parameter enables testing without filesystem access.

---

## 2. Synonym File

Location: `config/synonyms.yaml`

Format: a YAML list of lists. Each inner list is a group of equivalent terms.

```yaml
- [server, host, machine, node]
- [network, networking, net, lan, wan]
- [storage, disk, drive, volume, hdd, ssd, nas]
- [container, docker, pod, instance]
- [database, db, datastore, sql]
```

To add a new group: append a new list entry. Terms are matched lowercase. Changes take effect on next server restart (the synonym map is cached in memory).

---

## 3. Hybrid Search with Reciprocal Rank Fusion

Source: `flask_app/services/search.py::hybrid_search()`

`hybrid_search(query, k=10, client=None, llm_session=None)` runs BM25 and vector search in parallel using `concurrent.futures.ThreadPoolExecutor`, then fuses the ranked lists with Reciprocal Rank Fusion (RRF).

### RRF formula

For each document `d` at rank `r` (0-indexed) in list `L`:

```
score(d) += 1 / (K + r)    where K = 60
```

Documents appearing in both the BM25 and vector lists accumulate score from both. The fused list is sorted by descending score and the top-k documents are returned, each with an added `rrf_score` field.

### Why K = 60

A value of 60 is the standard in the original RRF paper (Cormack et al., 2009). It prevents a single top-ranked document from dominating when the two lists disagree strongly, while still giving meaningful weight to the top positions.

### Result shape

Each result dict mirrors an OpenSearch hit (`_id`, `_source`, `_score`) plus:

| Field | Type | Description |
|---|---|---|
| `rrf_score` | float | Combined reciprocal rank score from both lists |

---

## 4. Fallback Behaviour

| Condition | Behaviour |
|---|---|
| LLM API unavailable (`get_embedding` returns None) | Falls back to BM25-only results; no exception raised |
| BM25 raises | Empty result list returned; warning logged |
| Synonym file absent or unreadable | `expand_synonyms` returns the input unchanged; warning logged |
| Empty query | Pipeline functions return the input unchanged; OpenSearch not called |

When the LLM API is unavailable the search route continues to return BM25 results. The semantic rail warning in the UI reflects partial availability rather than total unavailability.

---

## 5. Known Limitations

- **Synonym cache**: the synonym map is loaded once at import time and held in memory. Changes to `config/synonyms.yaml` require a server restart.
- **Hybrid search pagination**: `hybrid_search()` returns a flat top-k list without server-side pagination. The HTML search route continues to use `bm25_body()` with OpenSearch `from`/`size` pagination for the main results column; `hybrid_search()` is available for callers that do not require deep pagination.
- **Stopword set**: the current set is English-only. Multilingual deployments should expand or replace the set.
- **Synonym expansion order**: synonyms are appended after the original query. OpenSearch assigns lower weight to later terms in a `multi_match` query via BM25 IDF, which is the desired behaviour.
