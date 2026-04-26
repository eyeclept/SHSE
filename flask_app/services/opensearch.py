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
        crawled_at      date        ingest timestamp
        service_nickname keyword    user-defined label
        content_type    keyword     MIME type
        vectorized      boolean     false until LLM API processes the chunk
        source_type     keyword     ingest method (nutch, oai-pmh, rss, api-push)
        content_hash    keyword     sha256 of chunk text; used for idempotent upsert

    Chunk size: 800 tokens
    Embedding model: nomic-embed-text (768 dimensions)
"""
# Imports
import os
from opensearchpy import OpenSearch, RequestsHttpConnection

# Globals
INDEX_NAME = "shse_pages"
EMBEDDING_DIM = 768

INDEX_BODY = {
    "settings": {
        "index": {
            "knn": True,
            "number_of_shards": 1,
            "number_of_replicas": 0,
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
            "service_nickname": {"type": "keyword"},
            "content_type":     {"type": "keyword"},
            "vectorized":       {"type": "boolean"},
            "source_type":      {"type": "keyword"},
            "content_hash":     {"type": "keyword"},
        }
    },
}

# Functions
def get_client():
    """
    Input: None
    Output: OpenSearch client instance
    Details:
        Reads connection parameters from environment variables. Uses HTTPS
        and basic auth against the OpenSearch security plugin.
    """
    host = os.environ.get("OPENSEARCH_HOST", "localhost")
    port = int(os.environ.get("OPENSEARCH_PORT", 9200))
    user = os.environ.get("OPENSEARCH_USER", "admin")
    password = os.environ.get("OPENSEARCH_INITIAL_ADMIN_PASSWORD", "")

    return OpenSearch(
        hosts=[{"host": host, "port": port}],
        http_auth=(user, password),
        use_ssl=True,
        verify_certs=False,
        connection_class=RequestsHttpConnection,
    )


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
        return {"acknowledged": True, "index": INDEX_NAME, "already_exists": True}

    return client.indices.create(index=INDEX_NAME, body=INDEX_BODY)


def _chunk_text(text, chunk_size=800):
    """
    Input: text — string to split; chunk_size — max tokens per chunk (default 800)
    Output: list of non-empty string chunks
    Details:
        Splits on whitespace. Each whitespace-delimited word counts as one token.
        This is an approximation; actual subword tokens average ~0.75 words each,
        so 800 words is a conservative upper bound that fits within an 800-token
        context window.
    """
    words = text.split()
    return [
        " ".join(words[i : i + chunk_size])
        for i in range(0, len(words), chunk_size)
        if words[i : i + chunk_size]
    ]


def index_document(url, port, title, crawled_at, service_nickname, content_type, text,
                   embeddings=None, chunk_size=800, source_type=None, client=None):
    """
    Input: url, port, title, crawled_at, service_nickname, content_type — document metadata;
           text — full document text to chunk and index;
           embeddings — optional list of vectors, one per chunk; None triggers deferred path;
           chunk_size — tokens per chunk (default 800);
           source_type — ingest method label (e.g. "nutch", "oai-pmh", "rss", "api-push");
           client — optional OpenSearch client
    Output: list of OpenSearch index response dicts, one per written chunk; skipped chunks absent
    Details:
        Splits text into chunk_size-word chunks. Document ID is sha256(url + chunk_index),
        making every write an idempotent upsert. If an existing document with the same ID
        already holds the same content_hash, the write is skipped (no-op). When embeddings
        is provided, each chunk is stored with its vector and vectorized=true. When None
        (LLM API unavailable or not yet run), chunks are stored with embedding=null and
        vectorized=false for deferred processing. Indexing always proceeds regardless of
        embedding availability.
    """
    import hashlib
    from opensearchpy.exceptions import NotFoundError

    if client is None:
        client = get_client()

    chunks = _chunk_text(text, chunk_size)
    responses = []
    for i, chunk in enumerate(chunks):
        doc_id = hashlib.sha256(f"{url}{i}".encode()).hexdigest()
        content_hash = hashlib.sha256(chunk.encode()).hexdigest()

        try:
            existing = client.get(index=INDEX_NAME, id=doc_id)
            if existing["_source"].get("content_hash") == content_hash:
                continue
        except NotFoundError:
            pass

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
            "service_nickname": service_nickname,
            "content_type": content_type,
            "text": chunk,
            "embedding": embedding,
            "vectorized": vectorized,
            "source_type": source_type,
            "content_hash": content_hash,
        }
        resp = client.index(index=INDEX_NAME, id=doc_id, body=doc)
        responses.append(resp)
    return responses


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
            "multi_match": {
                "query": query,
                "fields": ["title^2", "text"],
                "type": "best_fields",
                "fuzziness": "AUTO",
                "prefix_length": 1,
            }
        },
    }

    response = client.search(index=INDEX_NAME, body=body)
    return response["hits"]["hits"]


def get_unvectorized(page=0, page_size=100, client=None):
    """
    Input: page — zero-based page number (default 0);
           page_size — documents per page (default 100);
           client — optional OpenSearch client
    Output: list of hit dicts (each contains _id and _source fields)
    Details:
        Returns a single page of documents where vectorized=false, ordered by
        _doc for stable pagination. Callers increment page until an empty list
        is returned to drain the full unvectorized set.
    """
    if client is None:
        client = get_client()

    body = {
        "from": page * page_size,
        "size": page_size,
        "query": {
            "term": {
                "vectorized": False,
            }
        },
        "sort": [{"_doc": "asc"}],
    }

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
    return client.delete_by_query(index=INDEX_NAME, body=body)


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

    return client.delete_by_query(index=INDEX_NAME, body=body)


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

    return client.delete_by_query(index=INDEX_NAME, body=body)


if __name__ == "__main__":
    resp = create_index()
    print(resp)
