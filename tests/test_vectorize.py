"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Unit tests for celery_worker/tasks/vectorize.py — the embedding backfill.
    All tests use a mock OpenSearch client and a patched embedder; no live
    OpenSearch or LLM API required.
"""
# Imports
from unittest.mock import MagicMock, patch


# Functions
def test_vectorize_pending_uses_one_bulk_per_page():
    """
    Input: one page of two unvectorized docs, embedder returns a vector
    Output: a single client.bulk() call carrying both updates; client.update
            is never used
    Details:
        Regression test for efficiency finding #6 (backfill updated OpenSearch
        one document at a time). Each page must be written in a single bulk
        request.
    """
    from celery_worker.tasks import vectorize

    page1 = [
        {"_id": "d1", "_source": {"text": "alpha"}, "sort": [1]},
        {"_id": "d2", "_source": {"text": "beta"}, "sort": [2]},
    ]
    mock_client = MagicMock()
    mock_client.bulk.return_value = {
        "errors": False,
        "items": [{"update": {"_id": "d1", "status": 200}},
                  {"update": {"_id": "d2", "status": 200}}],
    }

    with patch("flask_app.services.opensearch.get_unvectorized",
               side_effect=[page1, []]), \
         patch("celery_worker.tasks.vectorize._embed_text", return_value=[0.1] * 768):
        vectorized, attempted = vectorize._vectorize_pending_impl(os_client=mock_client)

    assert attempted == 2
    assert vectorized == 2
    mock_client.update.assert_not_called()
    assert mock_client.bulk.call_count == 1

    body = mock_client.bulk.call_args.kwargs.get("body") or mock_client.bulk.call_args.args[0]
    assert len(body) == 4  # 2 docs × (action line + doc line)
    assert body[0] == {"update": {"_index": vectorize._INDEX_NAME, "_id": "d1"}}
    assert body[1] == {"doc": {"embedding": [0.1] * 768, "vectorized": True}}
    assert body[2] == {"update": {"_index": vectorize._INDEX_NAME, "_id": "d2"}}


def test_vectorize_pending_skips_bulk_when_embedding_unavailable():
    """
    Input: one page of docs but the embedder returns None (LLM API down)
    Output: no bulk call; attempted counted, vectorized stays 0 (deferred)
    """
    from celery_worker.tasks import vectorize

    page1 = [{"_id": "d1", "_source": {"text": "alpha"}, "sort": [1]}]
    mock_client = MagicMock()

    with patch("flask_app.services.opensearch.get_unvectorized",
               side_effect=[page1, []]), \
         patch("celery_worker.tasks.vectorize._embed_text", return_value=None):
        vectorized, attempted = vectorize._vectorize_pending_impl(os_client=mock_client)

    assert attempted == 1
    assert vectorized == 0
    mock_client.bulk.assert_not_called()
    mock_client.update.assert_not_called()


def test_vectorize_pending_counts_only_successful_bulk_items():
    """
    Input: a page of two docs where the bulk response reports one item failed
    Output: vectorized counts only the successful item
    """
    from celery_worker.tasks import vectorize

    page1 = [
        {"_id": "d1", "_source": {"text": "alpha"}, "sort": [1]},
        {"_id": "d2", "_source": {"text": "beta"}, "sort": [2]},
    ]
    mock_client = MagicMock()
    mock_client.bulk.return_value = {
        "errors": True,
        "items": [{"update": {"_id": "d1", "status": 200}},
                  {"update": {"_id": "d2", "status": 429, "error": "rejected"}}],
    }

    with patch("flask_app.services.opensearch.get_unvectorized",
               side_effect=[page1, []]), \
         patch("celery_worker.tasks.vectorize._embed_text", return_value=[0.1] * 768):
        vectorized, attempted = vectorize._vectorize_pending_impl(os_client=mock_client)

    assert attempted == 2
    assert vectorized == 1
    assert mock_client.bulk.call_count == 1


if __name__ == "__main__":
    pass
