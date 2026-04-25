"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Vectorize task. Backfills embeddings for documents that were indexed
    without a vector (vectorized=false) because the LLM API was unavailable at
    index time.
"""
# Imports
from celery_worker.app import celery

# Globals
_INDEX_NAME = "shse_pages"


# Functions
def _build_app_context():
    """
    Input: None
    Output: (Flask app, db)
    Details:
        Deferred import avoids circular import at module load time.
    """
    from flask_app import create_app, db as _db
    return create_app(), _db


def _vectorize_pending_impl(os_client=None, llm_session=None, page_size=100):
    """
    Input:
        os_client  - optional OpenSearch client (injectable for tests)
        llm_session - optional requests.Session for LLM API (injectable for tests)
        page_size  - documents per pagination page (default 100)
    Output:
        int — number of documents successfully vectorized
    Details:
        Paginates through docs where vectorized=false using get_unvectorized().
        For each doc, calls get_embedding() on its text field. If an embedding
        is returned, issues a partial update (doc.embedding + doc.vectorized=true).
        Docs where get_embedding() returns None are left unchanged (LLM API down).
    """
    from flask_app.services.opensearch import get_unvectorized, get_client
    from flask_app.services.llm import get_embedding

    client = os_client or get_client()
    vectorized_count = 0
    page = 0

    while True:
        hits = get_unvectorized(page=page, page_size=page_size, client=client)
        if not hits:
            break

        for hit in hits:
            doc_id = hit["_id"]
            text = hit.get("_source", {}).get("text", "")
            embedding = get_embedding(text, session=llm_session)
            if embedding is None:
                continue
            client.update(
                index=_INDEX_NAME,
                id=doc_id,
                body={"doc": {"embedding": embedding, "vectorized": True}},
            )
            vectorized_count += 1

        page += 1

    return vectorized_count


@celery.task
def vectorize_pending(_os_client=None, _llm_session=None, _page_size=100):
    """
    Input:
        _os_client   - injectable OpenSearch client (tests only)
        _llm_session - injectable requests.Session for LLM API (tests only)
        _page_size   - injectable page size (tests only)
    Output:
        int — number of documents successfully vectorized
    Details:
        Celery task wrapper for _vectorize_pending_impl. No Flask app context
        required — only OpenSearch and LLM API are accessed.
    """
    return _vectorize_pending_impl(
        os_client=_os_client,
        llm_session=_llm_session,
        page_size=_page_size,
    )


if __name__ == "__main__":
    pass
