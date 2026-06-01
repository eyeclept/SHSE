"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for flask_app/services/search.py hybrid_search() function.
    All OpenSearch and LLM calls are mocked; no live services required.
"""
# Imports
from unittest.mock import MagicMock, patch

import pytest


# Functions
def _make_hit(doc_id, score=1.0, title="Title", url="http://host/page", service="svc"):
    return {
        "_id": doc_id,
        "_score": score,
        "_source": {
            "title": title,
            "url": url,
            "service_nickname": service,
            "text": f"text for {doc_id}",
            "port": 80,
            "crawled_at": "2026-04-01T00:00:00",
            "content_type": "text/html",
            "vectorized": True,
        },
    }


def test_hybrid_rrf_interleaves_bm25_and_vector_hits():
    """
    Input:  BM25 returns doc A first; vector returns doc B first
    Output: both appear in fused results; doc appearing in both lists
            has a higher rrf_score than a doc appearing in only one list
    Details:
        RRF gives 1/(60+r) for each appearance. A doc appearing in both
        lists at rank 0 scores 2/60 ≈ 0.033, beating a doc at rank 0 in
        only one list which scores 1/60 ≈ 0.0166.
        Patch targets are the source modules because hybrid_search()
        imports bm25_search/vector_search/get_embedding inside the function.
    """
    bm25_hits = [_make_hit("A"), _make_hit("B"), _make_hit("C")]
    vec_hits = [_make_hit("A"), _make_hit("D")]

    mock_emb = [0.1] * 768

    with patch("flask_app.services.opensearch.bm25_search", return_value=bm25_hits), \
         patch("flask_app.services.opensearch.vector_search", return_value=vec_hits), \
         patch("flask_app.services.llm.get_embedding", return_value=mock_emb):
        from flask_app.services.search import hybrid_search
        results = hybrid_search("test query", k=10, client=MagicMock())

    ids = [r["_id"] for r in results]
    assert "A" in ids
    assert "B" in ids
    assert "D" in ids

    # A appears in both lists → highest score
    score_a = next(r["rrf_score"] for r in results if r["_id"] == "A")
    score_b = next(r["rrf_score"] for r in results if r["_id"] == "B")
    score_d = next(r["rrf_score"] for r in results if r["_id"] == "D")
    assert score_a > score_b
    assert score_a > score_d


def test_hybrid_rrf_scores_decrease_monotonically():
    """
    Input:  three unique docs in BM25, two unique docs in vector
    Output: rrf_scores of returned list are non-increasing
    """
    bm25_hits = [_make_hit(f"bm{i}") for i in range(5)]
    vec_hits = [_make_hit(f"vec{i}") for i in range(5)]

    mock_emb = [0.2] * 768

    with patch("flask_app.services.opensearch.bm25_search", return_value=bm25_hits), \
         patch("flask_app.services.opensearch.vector_search", return_value=vec_hits), \
         patch("flask_app.services.llm.get_embedding", return_value=mock_emb):
        from flask_app.services.search import hybrid_search
        results = hybrid_search("network config", k=10, client=MagicMock())

    scores = [r["rrf_score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_hybrid_fallback_to_bm25_when_embedding_is_none():
    """
    Input:  get_embedding returns None (LLM API down)
    Output: results contain only BM25 hits; no exception raised
    """
    bm25_hits = [_make_hit("X"), _make_hit("Y")]

    with patch("flask_app.services.opensearch.bm25_search", return_value=bm25_hits), \
         patch("flask_app.services.llm.get_embedding", return_value=None):
        from flask_app.services.search import hybrid_search
        results = hybrid_search("storage backup", k=10, client=MagicMock())

    ids = [r["_id"] for r in results]
    assert "X" in ids
    assert "Y" in ids


def test_hybrid_result_has_rrf_score_field():
    """
    Input:  any non-empty result set
    Output: every result dict has an 'rrf_score' float field
    """
    bm25_hits = [_make_hit("Z")]
    mock_emb = [0.3] * 768

    with patch("flask_app.services.opensearch.bm25_search", return_value=bm25_hits), \
         patch("flask_app.services.opensearch.vector_search", return_value=[]), \
         patch("flask_app.services.llm.get_embedding", return_value=mock_emb):
        from flask_app.services.search import hybrid_search
        results = hybrid_search("query", k=5, client=MagicMock())

    assert len(results) > 0
    for r in results:
        assert "rrf_score" in r
        assert isinstance(r["rrf_score"], float)


def test_hybrid_empty_results_when_both_sources_empty():
    """
    Input:  both BM25 and vector return empty lists
    Output: empty result list; no exception
    """
    mock_emb = [0.1] * 768

    with patch("flask_app.services.opensearch.bm25_search", return_value=[]), \
         patch("flask_app.services.opensearch.vector_search", return_value=[]), \
         patch("flask_app.services.llm.get_embedding", return_value=mock_emb):
        from flask_app.services.search import hybrid_search
        results = hybrid_search("empty query", k=10, client=MagicMock())

    assert results == []


def test_get_vector_hits_returns_hits_and_true():
    """
    Input:  embedding succeeds; vector_search returns two hits
    Output: (hits, True) — hits populated, embedding_available=True
    """
    mock_hits = [
        _make_hit("v1", score=0.9),
        _make_hit("v2", score=0.7),
    ]
    mock_emb = [0.1] * 768

    with patch("flask_app.services.llm.get_embedding", return_value=mock_emb), \
         patch("flask_app.services.opensearch.vector_search", return_value=mock_hits):
        from flask_app.services.search import get_vector_hits
        hits, available = get_vector_hits("server config", os_client=MagicMock())

    assert available is True
    assert len(hits) == 2
    assert hits[0]["score"] == 0.9
    for h in hits:
        assert "snippet" in h
        assert "context" in h
        assert "title" in h
        assert "service" in h
        assert "url" in h


def test_get_vector_hits_returns_dummy_and_false_when_embedding_down():
    """
    Input:  get_embedding returns None; get_cpu_embedding also returns None
    Output: ([], False) — both embedding tiers failed
    """
    with patch("flask_app.services.llm.get_embedding", return_value=None), \
         patch("flask_app.services.llm.get_cpu_embedding", return_value=None):
        from flask_app.services.search import get_vector_hits
        hits, available = get_vector_hits("server config", os_client=MagicMock())

    assert available is False
    assert hits == []


def test_get_vector_hits_uses_cpu_fallback_when_api_down():
    """
    Input:  get_embedding returns None (LLM API down);
            CPU_EMBED_FALLBACK enabled; get_cpu_embedding returns a valid vector
    Output: (hits, True) — CPU embedding used; real vector results returned
    """
    mock_hits = [_make_hit("c1", score=0.85)]
    mock_emb = [0.2] * 768

    with patch("flask_app.services.llm.get_embedding", return_value=None), \
         patch("flask_app.services.llm.get_cpu_embedding", return_value=mock_emb), \
         patch("flask_app.services.opensearch.vector_search", return_value=mock_hits), \
         patch("flask_app.config.Config.CPU_EMBED_FALLBACK", True):
        from flask_app.services.search import get_vector_hits
        hits, available = get_vector_hits("server config", os_client=MagicMock())

    assert available is True
    assert len(hits) == 1
    assert hits[0]["score"] == 0.85
    for key in ("snippet", "context", "title", "service", "url"):
        assert key in hits[0]


def test_get_vector_hits_skips_cpu_fallback_when_disabled():
    """
    Input:  get_embedding returns None; CPU_EMBED_FALLBACK=false (default)
    Output: ([], False) — semantic rail empty, CPU fallback not attempted
    """
    with patch("flask_app.services.llm.get_embedding", return_value=None), \
         patch("flask_app.config.Config.CPU_EMBED_FALLBACK", False):
        from flask_app.services.search import get_vector_hits
        hits, available = get_vector_hits("server config", os_client=MagicMock())

    assert available is False
    assert hits == []


def test_hybrid_bm25_failure_returns_empty():
    """
    Input:  BM25 raises; embedding also None
    Output: empty list; no exception propagated
    """
    with patch("flask_app.services.opensearch.bm25_search", side_effect=Exception("OS down")), \
         patch("flask_app.services.llm.get_embedding", return_value=None):
        from flask_app.services.search import hybrid_search
        results = hybrid_search("query", k=5, client=MagicMock())

    assert results == []


def test_bm25_body_service_filter():
    """
    Input:  filter_services=["kiwix"]
    Output: body query is a bool with a terms filter on service_nickname
    """
    from flask_app.services.search import bm25_body
    body = bm25_body("test query", filter_services=["kiwix"])
    bool_q = body["query"]["bool"]
    assert bool_q["must"]["multi_match"]["query"] == "test query"
    filters = bool_q["filter"]
    assert len(filters) == 1
    assert filters[0]["terms"]["service_nickname"] == ["kiwix"]


def test_bm25_body_sort_date_desc():
    """
    Input:  sort="date_desc"
    Output: body contains sort block with crawled_at desc followed by _score
    """
    from flask_app.services.search import bm25_body
    body = bm25_body("test query", sort="date_desc")
    assert "sort" in body
    assert body["sort"][0] == {"crawled_at": "desc"}
    assert body["sort"][1] == "_score"


def test_get_vector_hits_opensearch_exception_logs_exception():
    """
    Input:  vector_search raises an unexpected exception (e.g. 400 from OpenSearch)
    Output: logger.exception called; function returns ([], False) without propagating
    Details:
        Regression for Epic 29 — unexpected OpenSearch errors must use logger.exception
        not logger.warning so the full traceback is captured at ERROR level.
    """
    mock_emb = [0.1] * 768

    with patch("flask_app.services.llm.get_embedding", return_value=mock_emb), \
         patch("flask_app.services.opensearch.vector_search",
               side_effect=Exception("400 field mapping error")), \
         patch("flask_app.services.search.logger") as mock_logger:
        from flask_app.services.search import get_vector_hits
        hits, available = get_vector_hits("query", os_client=MagicMock())

    assert available is False
    assert hits == []
    mock_logger.exception.assert_called_once()
    args = mock_logger.exception.call_args[0]
    assert "get_vector_hits" in args[0]


def test_hybrid_bm25_exception_logs_exception():
    """
    Input:  bm25_search raises an unexpected exception inside hybrid_search
    Output: logger.exception called; result is still a list (degraded, not crashed)
    Details:
        Regression for Epic 29.
    """
    mock_emb = [0.1] * 768

    with patch("flask_app.services.opensearch.bm25_search",
               side_effect=Exception("OS 400 bad_request")), \
         patch("flask_app.services.opensearch.vector_search", return_value=[]), \
         patch("flask_app.services.llm.get_embedding", return_value=mock_emb), \
         patch("flask_app.services.search.logger") as mock_logger:
        from flask_app.services.search import hybrid_search
        results = hybrid_search("query", k=5, client=MagicMock())

    assert isinstance(results, list)
    mock_logger.exception.assert_called()
    logged_msgs = [call[0][0] for call in mock_logger.exception.call_args_list]
    assert any("BM25" in m for m in logged_msgs)


def test_hybrid_vector_exception_logs_exception():
    """
    Input:  vector_search raises an unexpected exception inside hybrid_search
    Output: logger.exception called; BM25 results still returned
    Details:
        Regression for Epic 29.
    """
    bm25_hits = [_make_hit("A")]
    mock_emb = [0.1] * 768

    with patch("flask_app.services.opensearch.bm25_search", return_value=bm25_hits), \
         patch("flask_app.services.opensearch.vector_search",
               side_effect=Exception("knn field not found")), \
         patch("flask_app.services.llm.get_embedding", return_value=mock_emb), \
         patch("flask_app.services.search.logger") as mock_logger:
        from flask_app.services.search import hybrid_search
        results = hybrid_search("query", k=5, client=MagicMock())

    assert isinstance(results, list)
    mock_logger.exception.assert_called()
    logged_msgs = [call[0][0] for call in mock_logger.exception.call_args_list]
    assert any("Vector" in m or "vector" in m for m in logged_msgs)


def test_build_ai_summary_bm25_failure_logs_exception():
    """
    Input:  bm25_search raises inside _build_ai_summary
    Output: logger.exception called; function returns None (no context → no summary)
    Details:
        Regression for Epic 29.
    """
    with patch("flask_app.services.opensearch.bm25_search",
               side_effect=Exception("OS request_error")), \
         patch("flask_app.services.opensearch.get_client", return_value=MagicMock()), \
         patch("flask_app.services.search.logger") as mock_logger:
        from flask_app.services.search import _build_ai_summary
        result = _build_ai_summary([], "what is dns")

    mock_logger.exception.assert_called_once()
    args = mock_logger.exception.call_args[0]
    assert "BM25" in args[0] or "bm25" in args[0].lower()
