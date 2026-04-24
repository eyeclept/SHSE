# OpenSearch Integration

## Index Schema

Index name: `shse_pages`

| Field | Type | Description |
|---|---|---|
| `url` | `keyword` | Source URL of the crawled page |
| `port` | `integer` | Source port |
| `text` | `text` | Chunk content — BM25 target field |
| `embedding` | `knn_vector` (768-dim) | Cosine similarity vector; `null` when deferred |
| `title` | `text` | Page title from Nutch |
| `crawled_at` | `date` | Ingest timestamp (ISO 8601) |
| `service_nickname` | `keyword` | User-defined label for the source service |
| `content_type` | `keyword` | MIME type |
| `vectorized` | `boolean` | `false` until LLM API processes the chunk |
| `source_type` | `keyword` | Ingest method: `nutch`, `oai-pmh`, `rss`, `api-push` |
| `content_hash` | `keyword` | SHA-256 of the chunk text; used for idempotent upsert |

Index settings: `knn=true`, `number_of_shards=1`, `number_of_replicas=0` (single-node dev cluster).

---

## BM25 and Vector Query Shapes

### BM25 (`bm25_search`)

```python
from flask_app.services.opensearch import bm25_search

hits = bm25_search("nginx reverse proxy", k=10)
# hits: list of dicts with _score and _source
```

Underlying query:

```json
{
  "size": 10,
  "query": {
    "match": {
      "text": { "query": "nginx reverse proxy" }
    }
  }
}
```

### Vector search (`vector_search`)

```python
from flask_app.services.opensearch import vector_search

hits = vector_search(query_embedding=[0.1, ...], k=10)
```

Underlying query:

```json
{
  "size": 10,
  "query": {
    "knn": {
      "embedding": {
        "vector": [0.1, ...],
        "k": 10
      }
    }
  }
}
```

Only documents with `vectorized=true` have a non-null embedding and participate in knn ranking.

---

## Chunking Strategy

Documents are split into 800-word chunks before indexing (`_chunk_text`). Word count is used as a proxy for subword tokens — 800 whitespace-delimited words is a conservative upper bound on an 800 subword-token context window. No external tokenizer is required.

Each chunk is indexed as a separate document, carrying the full set of metadata fields (`url`, `port`, `title`, `crawled_at`, `service_nickname`, `content_type`, `source_type`, `content_hash`).

---

## Idempotent Upsert

Every chunk is written with a deterministic document ID:

```
doc_id = sha256(url + str(chunk_index))
```

Before each write, `index_document` fetches the existing document by ID and compares its stored `content_hash` against the hash of the incoming chunk. If the hashes match, the write is skipped — no duplicate is created and no unnecessary I/O is performed. If the hashes differ (content changed) or no document exists (new chunk), the document is written using `client.index(id=doc_id, ...)`.

```python
from flask_app.services.opensearch import index_document

index_document(
    url="http://host/page",
    port=80,
    title="My Page",
    crawled_at="2026-04-23T10:00:00",
    service_nickname="my-svc",
    content_type="text/html",
    text=full_page_text,
    source_type="nutch",
)
# Re-running with identical text produces no writes.
# Re-running with changed text overwrites only the changed chunks.
```

---

## Deferred Vectorization Flow

When the LLM API is unavailable at index time, `index_document` is called without the `embeddings` argument (or with `embeddings=None`). Every chunk is stored with:

```json
{ "vectorized": false, "embedding": null }
```

Indexing always proceeds regardless of embedding availability. The `vectorize_pending` Celery task (Epic 9) later paginates over `vectorized=false` documents using `get_unvectorized(page, page_size)`, calls the LLM API for each batch, and updates the stored documents with their vectors.

### Pagination helper (`get_unvectorized`)

```python
from flask_app.services.opensearch import get_unvectorized

page = 0
while True:
    hits = get_unvectorized(page=page, page_size=100)
    if not hits:
        break
    # process hits ...
    page += 1
```

Results are ordered by `_doc` (insertion order) for stable pagination across calls.

---

## Index Management

### Stale document removal (`delete_stale`)

At the end of each crawl run, call `delete_stale` to purge pages that no longer exist on the target. Any document whose `crawled_at` is before the run-start timestamp and whose `service_nickname` matches is deleted.

```python
from flask_app.services.opensearch import delete_stale

# Call after all current pages have been upserted
delete_stale("my-svc", run_start="2026-04-23T10:00:00")
```

Underlying query:

```json
{
  "query": {
    "bool": {
      "must": [
        { "term": { "service_nickname": "my-svc" } },
        { "range": { "crawled_at": { "lt": "2026-04-23T10:00:00" } } }
      ]
    }
  }
}
```

### Delete by service nickname (`delete_by_nickname`)

Removes all documents for a service regardless of age. Use for full reindex or target removal.

```python
from flask_app.services.opensearch import delete_by_nickname

delete_by_nickname("my-service")
```

### Wipe entire index (`wipe_index`)

Deletes all documents using a `match_all` query. The index structure (settings and mappings) is preserved.

```python
from flask_app.services.opensearch import wipe_index

wipe_index()
```

### Create index (`create_index`)

Idempotent — safe to call on every startup. Returns immediately if the index already exists.

```python
from flask_app.services.opensearch import create_index

create_index()
```
