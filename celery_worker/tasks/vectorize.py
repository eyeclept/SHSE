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
from datetime import datetime

from celery.utils.log import get_task_logger
from celery_worker.app import celery

# Globals
_INDEX_NAME = "shse_pages"
logger = get_task_logger(__name__)


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
        os_client   - optional OpenSearch client (injectable for tests)
        llm_session - optional requests.Session for LLM API (injectable for tests)
        page_size   - documents per pagination page (default 100)
    Output:
        tuple (vectorized_count, attempted_count)
        vectorized_count - docs successfully embedded and updated
        attempted_count  - total docs found with vectorized=false
    Details:
        Phase 1: collects all unvectorized doc IDs and text via paginated reads
        with no updates happening, so the from/size offsets remain stable.
        Phase 2: processes the collected list, calling get_embedding() per doc
        and issuing a partial update on success. Separating read from write
        avoids a skip bug: updating docs during from/size pagination removes
        them from the result set, causing the next page's offset to jump over
        docs that shifted into the vacated positions.
        Docs where get_embedding() returns None are left unchanged (LLM API down).
        Callers use the tuple to distinguish success / partial / deferred outcomes.
    """
    from flask_app.services.opensearch import get_unvectorized, get_client
    from flask_app.services.llm import get_embedding

    client = os_client or get_client()

    # Phase 1: collect all unvectorized docs before any updates
    pending = []
    page = 0
    while True:
        hits = get_unvectorized(page=page, page_size=page_size, client=client)
        if not hits:
            break
        pending.extend(hits)
        page += 1

    attempted_count = len(pending)
    vectorized_count = 0

    # Phase 2: embed and update the collected list
    for hit in pending:
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

    return vectorized_count, attempted_count


@celery.task
def vectorize_pending(_os_client=None, _llm_session=None, _page_size=100, _db_session=None):
    """
    Input:
        _os_client   - injectable OpenSearch client (tests only)
        _llm_session - injectable requests.Session for LLM API (tests only)
        _page_size   - injectable page size (tests only)
        _db_session  - injectable SQLAlchemy session (tests only; skips CrawlJob tracking)
    Output:
        int — number of documents successfully vectorized
    Details:
        Creates a CrawlJob(kind='vectorize') row, runs _vectorize_pending_impl,
        and updates the job status on completion. When _db_session is provided
        (tests only), CrawlJob tracking is skipped.
    """
    if _db_session is not None:
        vectorized, attempted = _vectorize_pending_impl(
            os_client=_os_client, llm_session=_llm_session, page_size=_page_size,
        )
        return vectorized

    from flask_app import create_app, db as _db
    from flask_app.models.crawl_job import CrawlJob

    app = create_app()
    with app.app_context():
        job = CrawlJob(kind="vectorize", status="started", started_at=datetime.utcnow())
        _db.session.add(job)
        _db.session.commit()
        logger.info("CrawlJob %s started — kind=vectorize task_id=%s", job.id, job.task_id)

        try:
            vectorized, attempted = _vectorize_pending_impl(
                os_client=_os_client, llm_session=_llm_session, page_size=_page_size,
            )
            if attempted == 0:
                job.status = "success"
                job.message = "No documents pending vectorization"
            elif vectorized == attempted:
                job.status = "success"
                job.message = f"Vectorized {vectorized} document(s)"
            elif vectorized == 0:
                job.status = "deferred"
                job.message = f"LLM API unavailable — {attempted} document(s) pending vectorization"
            else:
                job.status = "partial"
                job.message = f"Vectorized {vectorized}/{attempted} document(s); LLM unavailable for remainder"
            job.finished_at = datetime.utcnow()
            logger.info("CrawlJob %s %s — %s", job.id, job.status, job.message)
        except Exception as exc:
            job.status = "failure"
            job.finished_at = datetime.utcnow()
            job.message = str(exc)[:500]
            logger.exception("CrawlJob %s failure — kind=vectorize", job.id)
            _db.session.commit()
            raise

        _db.session.commit()
        return vectorized


if __name__ == "__main__":
    pass
