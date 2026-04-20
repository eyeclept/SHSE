"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for Epic 5 (OpenSearch Integration): index creation, BM25 search,
    document chunking, deferred indexing, vector search, delete, wipe, and
    paginated unvectorized query.
"""
# Imports
from unittest.mock import MagicMock, patch
import pytest

from flask_app.services.opensearch import (
    INDEX_NAME,
    INDEX_BODY,
    EMBEDDING_DIM,
    create_index,
    bm25_search,
    vector_search,
    index_document,
    _chunk_text,
    delete_by_nickname,
    wipe_index,
    get_unvectorized,
)

# Globals

# Functions
@pytest.fixture
def mock_client():
    """
    Input: None
    Output: MagicMock standing in for an OpenSearch client
    Details:
        Provides a client double so tests never hit a live OpenSearch node.
    """
    return MagicMock()


def test_index_created(mock_client):
    """
    Input: mock_client fixture
    Output: None
    Details:
        Verifies create_index sends the correct mapping body and returns an
        acknowledged response when the index does not yet exist.
    """
    mock_client.indices.exists.return_value = False
    mock_client.indices.create.return_value = {
        "acknowledged": True,
        "shards_acknowledged": True,
        "index": INDEX_NAME,
    }

    resp = create_index(client=mock_client)

    mock_client.indices.exists.assert_called_once_with(index=INDEX_NAME)
    mock_client.indices.create.assert_called_once_with(index=INDEX_NAME, body=INDEX_BODY)
    assert resp["acknowledged"] is True
    assert resp["index"] == INDEX_NAME


def test_index_already_exists_is_noop(mock_client):
    """
    Input: mock_client fixture
    Output: None
    Details:
        Verifies create_index skips the create call and returns a stable
        response when the index already exists.
    """
    mock_client.indices.exists.return_value = True

    resp = create_index(client=mock_client)

    mock_client.indices.create.assert_not_called()
    assert resp["acknowledged"] is True
    assert resp.get("already_exists") is True


def test_index_schema_fields():
    """
    Input: None
    Output: None
    Details:
        Verifies the mapping constant contains all nine required fields with
        correct types. This test runs without a network connection.
    """
    props = INDEX_BODY["mappings"]["properties"]

    assert props["url"]["type"] == "keyword"
    assert props["port"]["type"] == "integer"
    assert props["text"]["type"] == "text"
    assert props["embedding"]["type"] == "knn_vector"
    assert props["embedding"]["dimension"] == EMBEDDING_DIM
    assert props["title"]["type"] == "text"
    assert props["crawled_at"]["type"] == "date"
    assert props["service_nickname"]["type"] == "keyword"
    assert props["content_type"]["type"] == "keyword"
    assert props["vectorized"]["type"] == "boolean"


def test_bm25(mock_client):
    """
    Input: mock_client fixture
    Output: None
    Details:
        Verifies bm25_search sends a match query against the text field and
        returns the hits list from the response.
    """
    fake_hits = [
        {"_score": 1.5, "_source": {"text": "hello world", "url": "http://a"}},
        {"_score": 0.9, "_source": {"text": "hello there", "url": "http://b"}},
    ]
    mock_client.search.return_value = {"hits": {"hits": fake_hits}}

    results = bm25_search("hello", k=5, client=mock_client)

    call_args = mock_client.search.call_args
    body = call_args.kwargs.get("body") or call_args.args[0] if call_args.args else call_args.kwargs["body"]
    assert body["size"] == 5
    assert body["query"]["match"]["text"]["query"] == "hello"
    assert results == fake_hits


def test_bm25_returns_empty_on_no_hits(mock_client):
    """
    Input: mock_client fixture
    Output: None
    Details:
        Verifies bm25_search returns an empty list when OpenSearch returns
        zero hits.
    """
    mock_client.search.return_value = {"hits": {"hits": []}}

    results = bm25_search("nonexistent", client=mock_client)

    assert results == []


def test_chunk_text_splits_at_boundary():
    """
    Input: None
    Output: None
    Details:
        Verifies _chunk_text splits a word list at exactly the given boundary
        and that no words are lost across all chunks.
    """
    words = ["word"] * 1700
    text = " ".join(words)
    chunks = _chunk_text(text, chunk_size=800)

    assert len(chunks) == 3                          # 800 + 800 + 100
    assert len(chunks[0].split()) == 800
    assert len(chunks[1].split()) == 800
    assert len(chunks[2].split()) == 100
    # no words lost
    total = sum(len(c.split()) for c in chunks)
    assert total == 1700


def test_chunk_text_empty_string():
    """
    Input: None
    Output: None
    Details:
        Verifies _chunk_text returns an empty list for an empty input string.
    """
    assert _chunk_text("") == []


def test_index_doc(mock_client):
    """
    Input: mock_client fixture
    Output: None
    Details:
        Verifies index_document splits text into 800-word chunks, calls
        client.index once per chunk, and stores vectorized=false and
        embedding=null on every chunk.
    """
    mock_client.index.return_value = {"result": "created", "_id": "abc"}

    words = ["token"] * 1600
    text = " ".join(words)

    responses = index_document(
        url="http://host/page",
        port=80,
        title="Test Page",
        crawled_at="2026-04-20T00:00:00",
        service_nickname="test-svc",
        content_type="text/html",
        text=text,
        chunk_size=800,
        client=mock_client,
    )

    # two chunks of 800 words each
    assert mock_client.index.call_count == 2
    assert len(responses) == 2

    for call in mock_client.index.call_args_list:
        doc = call.kwargs.get("body") or call.args[0]
        assert doc["vectorized"] is False
        assert doc["embedding"] is None
        assert doc["url"] == "http://host/page"
        assert doc["service_nickname"] == "test-svc"
        chunk_words = len(doc["text"].split())
        assert chunk_words == 800


def test_deferred_index(mock_client):
    """
    Input: mock_client fixture
    Output: None
    Details:
        Verifies that when embeddings=None (Ollama unavailable), index_document
        stores every chunk with vectorized=false and embedding=null and still
        calls client.index for each chunk without raising an exception.
    """
    mock_client.index.return_value = {"result": "created", "_id": "xyz"}

    words = ["word"] * 800
    text = " ".join(words)

    responses = index_document(
        url="http://host/page",
        port=443,
        title="Deferred Page",
        crawled_at="2026-04-20T00:00:00",
        service_nickname="svc",
        content_type="text/html",
        text=text,
        embeddings=None,
        client=mock_client,
    )

    assert mock_client.index.call_count == 1
    assert len(responses) == 1

    doc = mock_client.index.call_args.kwargs.get("body") or mock_client.index.call_args.args[0]
    assert doc["vectorized"] is False
    assert doc["embedding"] is None


def test_index_doc_with_embeddings(mock_client):
    """
    Input: mock_client fixture
    Output: None
    Details:
        Verifies that when embeddings are supplied, each chunk is stored with
        vectorized=true and the correct embedding vector.
    """
    mock_client.index.return_value = {"result": "created", "_id": "xyz"}

    fake_embedding = [0.1] * EMBEDDING_DIM
    words = ["word"] * 800
    text = " ".join(words)

    index_document(
        url="http://host/page",
        port=80,
        title="Vectorized Page",
        crawled_at="2026-04-20T00:00:00",
        service_nickname="svc",
        content_type="text/html",
        text=text,
        embeddings=[fake_embedding],
        client=mock_client,
    )

    doc = mock_client.index.call_args.kwargs.get("body") or mock_client.index.call_args.args[0]
    assert doc["vectorized"] is True
    assert doc["embedding"] == fake_embedding


def test_vector_search(mock_client):
    """
    Input: mock_client fixture
    Output: None
    Details:
        Verifies vector_search sends a knn query against the embedding field
        with the correct vector and k, and returns the hits list.
    """
    fake_hits = [
        {"_score": 0.98, "_source": {"text": "relevant chunk", "url": "http://a"}},
        {"_score": 0.85, "_source": {"text": "somewhat relevant", "url": "http://b"}},
    ]
    mock_client.search.return_value = {"hits": {"hits": fake_hits}}

    query_vec = [0.1] * EMBEDDING_DIM
    results = vector_search(query_vec, k=5, client=mock_client)

    call_args = mock_client.search.call_args
    body = call_args.kwargs.get("body") or call_args.args[0]
    assert body["size"] == 5
    assert body["query"]["knn"]["embedding"]["vector"] == query_vec
    assert body["query"]["knn"]["embedding"]["k"] == 5
    assert results == fake_hits


def test_paginate_unvectorized(mock_client):
    """
    Input: mock_client fixture
    Output: None
    Details:
        Verifies get_unvectorized sends a term query for vectorized=false with
        correct from/size offsets for page 0 and page 1, and returns the hits
        list. Also verifies an empty list is returned when no hits remain.
    """
    fake_hits = [
        {"_id": "1", "_source": {"text": "chunk one", "vectorized": False}},
        {"_id": "2", "_source": {"text": "chunk two", "vectorized": False}},
    ]
    mock_client.search.return_value = {"hits": {"hits": fake_hits}}

    # page 0
    results = get_unvectorized(page=0, page_size=2, client=mock_client)
    call_args = mock_client.search.call_args
    body = call_args.kwargs.get("body") or call_args.args[0]
    assert body["from"] == 0
    assert body["size"] == 2
    assert body["query"]["term"]["vectorized"] is False
    assert results == fake_hits

    # page 1
    get_unvectorized(page=1, page_size=2, client=mock_client)
    call_args = mock_client.search.call_args
    body = call_args.kwargs.get("body") or call_args.args[0]
    assert body["from"] == 2

    # empty page
    mock_client.search.return_value = {"hits": {"hits": []}}
    assert get_unvectorized(page=99, page_size=2, client=mock_client) == []


def test_wipe_index(mock_client):
    """
    Input: mock_client fixture
    Output: None
    Details:
        Verifies wipe_index sends a match_all delete-by-query and returns the
        response containing a deleted count. Confirms the index is targeted and
        that no query filter restricts the deletion.
    """
    mock_client.delete_by_query.return_value = {"deleted": 42, "failures": []}

    result = wipe_index(client=mock_client)

    call_args = mock_client.delete_by_query.call_args
    body = call_args.kwargs.get("body") or call_args.args[1]
    index_arg = call_args.kwargs.get("index") or call_args.args[0]
    assert index_arg == INDEX_NAME
    assert body["query"] == {"match_all": {}}
    assert result["deleted"] == 42
    assert result["failures"] == []


def test_delete_by_nickname(mock_client):
    """
    Input: mock_client fixture
    Output: None
    Details:
        Verifies delete_by_nickname sends a term query on service_nickname and
        that only documents matching that exact value would be deleted, confirmed
        by inspecting the query body passed to delete_by_query.
    """
    mock_client.delete_by_query.return_value = {"deleted": 3, "failures": []}

    result = delete_by_nickname("my-service", client=mock_client)

    call_args = mock_client.delete_by_query.call_args
    body = call_args.kwargs.get("body") or call_args.args[1]
    assert call_args.kwargs.get("index") == INDEX_NAME or call_args.args[0] == INDEX_NAME
    assert body["query"]["term"]["service_nickname"] == "my-service"
    assert result["deleted"] == 3
    assert result["failures"] == []


def test_vector_search_returns_empty_on_no_hits(mock_client):
    """
    Input: mock_client fixture
    Output: None
    Details:
        Verifies vector_search returns an empty list when OpenSearch returns
        zero hits.
    """
    mock_client.search.return_value = {"hits": {"hits": []}}

    results = vector_search([0.0] * EMBEDDING_DIM, client=mock_client)

    assert results == []
