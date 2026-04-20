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
        vectorized      boolean     false until Ollama processes the chunk

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
                   embeddings=None, chunk_size=800, client=None):
    """
    Input: url, port, title, crawled_at, service_nickname, content_type — document metadata;
           text — full document text to chunk and index;
           embeddings — optional list of vectors, one per chunk; None triggers deferred path;
           chunk_size — tokens per chunk (default 800);
           client — optional OpenSearch client
    Output: list of OpenSearch index response dicts, one per chunk
    Details:
        Splits text into chunk_size-word chunks. When embeddings is provided, each
        chunk is stored with its vector and vectorized=true. When embeddings is None
        (Ollama unavailable or not yet run), every chunk is stored with embedding=null
        and vectorized=false so the deferred vectorization task can process them later.
        Indexing always proceeds regardless of embedding availability.
    """
    if client is None:
        client = get_client()

    chunks = _chunk_text(text, chunk_size)
    responses = []
    for i, chunk in enumerate(chunks):
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
        }
        resp = client.index(index=INDEX_NAME, body=doc)
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
        Runs a BM25 match query against the text field and returns the top-k
        hits sorted by relevance score descending.
    """
    if client is None:
        client = get_client()

    body = {
        "size": k,
        "query": {
            "match": {
                "text": {
                    "query": query,
                }
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


if __name__ == "__main__":
    resp = create_index()
    print(resp)
