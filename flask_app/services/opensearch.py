"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    OpenSearch client. Handles BM25 search, vector search, document indexing,
    and index management (wipe, delete by target).

    Index schema:
        url             keyword     source URL
        port            integer     source port
        text            text        chunk content (BM25 target)
        embedding       knn_vector  cosine similarity; null if deferred
        title           text        page title from Nutch
        crawled_at      date        last time the crawler visited this URL (updated every crawl)
        last_changed_at date        last time the chunk content actually changed (null until first change detected)
        service_nickname keyword    user-defined label
        content_type    keyword     MIME type
        vectorized      boolean     false until LLM API processes the chunk
        source_type     keyword     ingest method (nutch, oai-pmh, rss, api-push)
        content_hash    keyword     sha256 of chunk text; used for idempotent upsert

    Chunk size: 800 tokens
    Embedding model: nomic-embed-text (768 dimensions)
"""
# Imports
import logging
import os
import threading
import tiktoken
from opensearchpy import OpenSearch, RequestsHttpConnection

# Globals
logger = logging.getLogger(__name__)
INDEX_NAME = "shse_pages"
EMBEDDING_DIM = 768

# Lazily-built, process-wide OpenSearch client. The opensearchpy client (and its
# underlying urllib3 connection pool) is thread-safe for concurrent requests and
# transparently reconnects after a node restart, so a single long-lived instance
# is reused across every request and Celery task instead of rebuilding the TLS
# pool on every call.
_client = None
_client_lock = threading.Lock()
_enc = tiktoken.get_encoding("cl100k_base")
_SAFE_EMBED_TOKENS = 1600  # conservative guard under nomic-embed-text's 2048-token limit

# Increment when _chunk_text algorithm changes (overlap, size, tokenizer).
# Stored on every chunk so stale chunks from old algorithms are detectable.
CHUNK_ALGO_VERSION = 2  # v1=non-overlapping 800w, v2=800w/50w-overlap+tiktoken

INDEX_BODY = {
    "settings": {
        "index": {
            "knn": True,
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "max_result_window": 100000,
        }
    },
    "mappings": {
        "properties": {
            "url":              {"type": "keyword"},
            "port":             {"type": "integer"},
            "text":             {"type": "text"},
            "embedding":        {"type": "knn_vector", "dimension": EMBEDDING_DIM},
            "title":            {"type": "text"},
            "crawled_at":       {"type": "date"},
            "last_changed_at":  {"type": "date"},
            "service_nickname": {"type": "keyword"},
            "content_type":     {"type": "keyword"},
            "vectorized":       {"type": "boolean"},
            "source_type":      {"type": "keyword"},
            "content_hash":     {"type": "keyword"},
            "chunk_algo":       {"type": "short"},
        }
    },
}

# Functions
def get_client():
    """
    Input: None
    Output: OpenSearch client instance
    Details:
        Returns a lazily-constructed, process-wide singleton client. The first
        call builds it from Config; later calls reuse the same instance so the
        TLS handshake and connection pool are set up once, not per request or
        per indexed document. Thread-safe via double-checked locking. Callers
        that need a different client (tests) still pass one explicitly.
    """
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            from flask_app.config import Config
            _client = OpenSearch(
                hosts=[{"host": Config.OPENSEARCH_HOST, "port": Config.OPENSEARCH_PORT}],
                http_auth=(Config.OPENSEARCH_USER, Config.OPENSEARCH_PASSWORD),
                use_ssl=True,
                verify_certs=False,
                connection_class=RequestsHttpConnection,
                # Fail fast instead of degrading slowly: a routable-but-dead node
                # (e.g. a powered-off VM whose subnet is still up) otherwise
                # triggers the default 4-attempt retry storm (~12s/call). One
                # attempt under the default 10s timeout keeps search responsive;
                # transient crawl/index blips are covered by Celery task retries.
                max_retries=0,
                retry_on_timeout=False,
            )
    return _client


def create_index(client=None):
    """
    Input: client — optional OpenSearch client; creates one if not supplied
    Output: dict — OpenSearch API response body
    Details:
        Creates the shse_pages index with full knn_vector schema. If the index
        already exists the call is a no-op and the existing index is returned.
    """
    if client is None:
        client = get_client()

    if client.indices.exists(index=INDEX_NAME):
        # Apply max_result_window even to pre-existing indexes — it's a dynamic
        # setting so no rebuild is required.
        client.indices.put_settings(
            index=INDEX_NAME,
            body={"index": {"max_result_window": 100000}},
        )
        return {"acknowledged": True, "index": INDEX_NAME, "already_exists": True}

    return client.indices.create(index=INDEX_NAME, body=INDEX_BODY)


def _append_safe_chunks(word_list, out):
    """
    Input: word_list — list of whitespace-split words; out — list to append to
    Output: None (appends to out in place)
    Details:
        Recursively halves word_list at the midpoint until each piece is within
        _SAFE_EMBED_TOKENS. Preserves word boundaries; never cuts a word in half.
        Used as a failover inside _chunk_text for chunks that would otherwise
        exceed nomic-embed-text's 2048-token architectural limit.
    """
    if not word_list:
        return
    text = " ".join(word_list)
    if len(_enc.encode(text)) <= _SAFE_EMBED_TOKENS or len(word_list) == 1:
        if text:
            out.append(text)
        return
    mid = len(word_list) // 2
    _append_safe_chunks(word_list[:mid], out)
    _append_safe_chunks(word_list[mid:], out)


def _chunk_text(text, chunk_size=800, overlap=50):
    """
    Input: text — string to split;
           chunk_size — target words per chunk (default 800);
           overlap — words shared between adjacent chunks (default 50)
    Output: list of non-empty string chunks
    Details:
        Overlapping word-based chunking. Adjacent chunks share `overlap` words
        so context is not abruptly cut at chunk boundaries (improves RAG
        retrieval quality). Chunk identity depends only on position (chunk_index),
        not content, so the idempotent upsert in index_document works correctly.
        If any chunk exceeds _SAFE_EMBED_TOKENS (measured by tiktoken cl100k_base),
        it is recursively halved at word boundaries via _append_safe_chunks.
        This handles dense technical content (code, URLs, mixed special characters)
        whose word count is 800 but whose subword token count can exceed 2048.
    """
    words = text.split()
    if not words:
        return []
    step = max(1, chunk_size - overlap)
    result = []
    i = 0
    while i < len(words):
        chunk_words = words[i : i + chunk_size]
        if not chunk_words:
            break
        _append_safe_chunks(chunk_words, result)
        if i + len(chunk_words) >= len(words):
            break
        i += step
    return result


def index_document(url, port, title, crawled_at, service_nickname, content_type, text,
                   embeddings=None, chunk_size=800, overlap=50, source_type=None, client=None):
    """
    Input: url, port, title, crawled_at, service_nickname, content_type — document metadata;
           text — full document text to chunk and index;
           embeddings — optional list of vectors, one per chunk; None triggers deferred path;
           chunk_size — target words per chunk (default 800);
           overlap — words shared between adjacent chunks (default 50);
           source_type — ingest method label (e.g. "nutch", "oai-pmh", "rss", "api-push");
           client — optional OpenSearch client
    Output: list of OpenSearch bulk response items, one per written chunk; skipped chunks absent
    Details:
        Splits text into overlapping word-based chunks via _chunk_text. Document ID is
        sha256(url + chunk_index), making every write an idempotent upsert. Uses mget to
        fetch all existing chunks in one round-trip, then bulk to write all changed chunks
        in one round-trip, replacing the previous N+1 individual GET/index calls.
        If an existing document with the same content_hash is unchanged, only crawled_at
        is updated. When embeddings is provided, each chunk is stored with its vector and
        vectorized=true. When None (LLM API unavailable), chunks are stored with
        embedding=null and vectorized=false for deferred processing.
    """
    import hashlib

    if client is None:
        client = get_client()

    chunks = _chunk_text(text, chunk_size, overlap)
    if not chunks:
        return []

    # Build all IDs and hashes upfront
    doc_ids = [hashlib.sha256(f"{url}{i}".encode()).hexdigest() for i in range(len(chunks))]
    content_hashes = [hashlib.sha256(c.encode()).hexdigest() for c in chunks]

    # Single mget to fetch all existing chunks
    mget_resp = client.mget(index=INDEX_NAME, body={"ids": doc_ids})
    existing = {d["_id"]: d for d in mget_resp["docs"]}

    # Build bulk body
    bulk_body = []
    for i, (chunk, doc_id, content_hash) in enumerate(zip(chunks, doc_ids, content_hashes)):
        ex = existing.get(doc_id, {})
        if ex.get("found"):
            src = ex.get("_source", {})
            if (src.get("content_hash") == content_hash
                    and src.get("chunk_algo") == CHUNK_ALGO_VERSION):
                # Content unchanged — bump crawled_at only via partial update
                bulk_body.append({"update": {"_index": INDEX_NAME, "_id": doc_id}})
                bulk_body.append({"doc": {"crawled_at": crawled_at}})
                continue

        if embeddings is not None and i < len(embeddings):
            embedding = embeddings[i]
            vectorized = True
        else:
            embedding = None
            vectorized = False

        doc = {
            "url": url,
            "port": port,
            "title": title,
            "crawled_at": crawled_at,
            "last_changed_at": crawled_at,
            "service_nickname": service_nickname,
            "content_type": content_type,
            "text": chunk,
            "embedding": embedding,
            "vectorized": vectorized,
            "source_type": source_type,
            "content_hash": content_hash,
            "chunk_algo": CHUNK_ALGO_VERSION,
        }
        bulk_body.append({"index": {"_index": INDEX_NAME, "_id": doc_id}})
        bulk_body.append(doc)

    if not bulk_body:
        return []

    resp = client.bulk(body=bulk_body)
    return resp.get("items", [])


def vector_search(query_embedding, k=10, client=None):
    """
    Input: query_embedding — list of floats (length EMBEDDING_DIM);
           k — max results to return (default 10);
           client — optional OpenSearch client
    Output: list of hit dicts (each contains _source fields and _score)
    Details:
        Runs a k-NN query against the embedding field using cosine similarity.
        The index must have been created with knn=true and the embedding field
        typed as knn_vector. Only documents with vectorized=true will have a
        non-null embedding and participate in the ranking.
    """
    if client is None:
        client = get_client()

    body = {
        "size": k,
        "query": {
            "knn": {
                "embedding": {
                    "vector": query_embedding,
                    "k": k,
                }
            }
        },
    }

    response = client.search(index=INDEX_NAME, body=body)
    return response["hits"]["hits"]


def bm25_search(query, k=10, client=None):
    """
    Input: query — search string; k — max results to return (default 10);
           client — optional OpenSearch client
    Output: list of hit dicts (each contains _source fields and _score)
    Details:
        Runs a multi_match best_fields query across `text` and `title` (title
        boosted 2x) with fuzziness=AUTO for typo tolerance. prefix_length=1
        prevents fuzzing the leading character to avoid overly broad matches.
    """
    if client is None:
        client = get_client()

    body = {
        "size": k,
        "query": {
            "bool": {
                "should": [
                    # Exact phrase in title scores highest — prevents fuzzy tokens
                    # (e.g. "America") from floating unrelated pages above the target.
                    {
                        "match_phrase": {
                            "title": {"query": query, "boost": 4},
                        }
                    },
                    {
                        "multi_match": {
                            "query": query,
                            "fields": ["title^2", "text"],
                            "type": "best_fields",
                            "fuzziness": "AUTO",
                            "prefix_length": 1,
                        }
                    },
                ]
            }
        },
    }

    response = client.search(index=INDEX_NAME, body=body)
    return response["hits"]["hits"]


def get_unvectorized(search_after=None, page_size=100, client=None):
    """
    Input: search_after — sort value list from the last hit of the previous page
                          (None for the first page);
           page_size — documents per page (default 100);
           client — optional OpenSearch client
    Output: list of hit dicts (each contains _id, _source, and sort fields)
    Details:
        Returns a single page of documents where vectorized=false, ordered by
        _doc for stable cursor-based pagination. Callers pass hits[-1]["sort"]
        as search_after on the next call until an empty list is returned.
        Uses search_after instead of from/size to avoid the 10 000-document
        max_result_window limit.
    """
    if client is None:
        client = get_client()

    body = {
        "size": page_size,
        "query": {
            "term": {
                "vectorized": False,
            }
        },
        "sort": [{"_doc": "asc"}],
    }
    if search_after is not None:
        body["search_after"] = search_after

    response = client.search(index=INDEX_NAME, body=body)
    return response["hits"]["hits"]


def wipe_index(client=None):
    """
    Input: client — optional OpenSearch client
    Output: dict — OpenSearch delete-by-query response (includes 'deleted' count)
    Details:
        Deletes all documents from the shse_pages index using a match_all query.
        The index itself is preserved; only its documents are removed.
    """
    if client is None:
        client = get_client()

    body = {"query": {"match_all": {}}}
    return client.delete_by_query(index=INDEX_NAME, body=body, params={"conflicts": "proceed"})


def delete_by_nickname(service_nickname, client=None):
    """
    Input: service_nickname — keyword value to match; client — optional OpenSearch client
    Output: dict — OpenSearch delete-by-query response (includes 'deleted' count)
    Details:
        Issues a delete-by-query against the term value of the service_nickname
        keyword field. Only documents whose service_nickname matches exactly are
        removed; all other documents are untouched.
    """
    if client is None:
        client = get_client()

    body = {
        "query": {
            "term": {
                "service_nickname": service_nickname,
            }
        }
    }

    return client.delete_by_query(index=INDEX_NAME, body=body, params={"conflicts": "proceed"})


def delete_stale(service_nickname, run_start, client=None):
    """
    Input: service_nickname — keyword value identifying the target;
           run_start — ISO 8601 timestamp string marking the beginning of the crawl run;
           client — optional OpenSearch client
    Output: dict — OpenSearch delete-by-query response (includes 'deleted' count)
    Details:
        Deletes all documents for a given service_nickname whose crawled_at timestamp
        is strictly before run_start. Call this at the end of a crawl run after all
        current pages have been upserted so that removed pages are purged from the index.
        Uses a bool/must query combining a term filter on service_nickname and a range
        filter on crawled_at.
    """
    if client is None:
        client = get_client()

    body = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"service_nickname": service_nickname}},
                    {"range": {"crawled_at": {"lt": run_start}}},
                ]
            }
        }
    }

    return client.delete_by_query(index=INDEX_NAME, body=body, params={"conflicts": "proceed"})


if __name__ == "__main__":
    resp = create_index()
    print(resp)
