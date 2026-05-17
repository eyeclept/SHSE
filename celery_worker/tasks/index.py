"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Reindex Celery tasks. Trigger a fresh crawl for one target or all targets.
    Stale document removal is handled by delete_stale() at the end of each crawl
    run — it removes only pages whose crawled_at timestamp predates the run start,
    meaning pages the current crawl did not visit. Pre-wiping before re-crawling
    is intentionally avoided: any page the crawler misses on a given run would be
    permanently lost if the index were cleared first.

    The "Drop and recreate index" operation in the admin UI (wipe_index +
    create_index) is the explicit full-reset path when a clean slate is needed.
"""
# Imports
from celery.utils.log import get_task_logger
from celery_worker.app import celery
from celery_worker.tasks.crawl import _crawl_target_impl, crawl_target

# Globals
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


@celery.task
def reindex_target(target_id, _db_session=None, _os_client=None,
                   _nutch_session=None):
    """
    Input:
        target_id     - int, CrawlerTarget primary key
        _db_session   - injectable SQLAlchemy session (tests only)
        _os_client    - injectable OpenSearch client (tests only)
        _nutch_session - injectable requests.Session for Nutch (tests only)
    Output: int — CrawlJob id created by the crawl run
    Details:
        Triggers a fresh crawl for the target. Pages that no longer exist are
        removed by delete_stale() at the end of the crawl (pages not visited in
        this run whose crawled_at predates run_start). Pages the crawler reaches
        are re-indexed with updated content and a refreshed crawled_at timestamp.
        The index is NOT pre-wiped — doing so would permanently lose any page the
        crawler happens to miss on this particular run.
    """
    def _impl(db_session):
        return _crawl_target_impl(target_id, db_session, _nutch_session, _os_client)

    if _db_session is not None:
        return _impl(_db_session)
    app, db = _build_app_context()
    with app.app_context():
        return _impl(db.session)


@celery.task
def reindex_all(_db_session=None, _os_client=None):
    """
    Input:
        _db_session - injectable SQLAlchemy session (tests only)
        _os_client  - injectable OpenSearch client (tests only)
    Output: list[str] — Celery AsyncResult IDs of dispatched crawl_target tasks
    Details:
        Dispatches crawl_target.delay() for every CrawlerTarget row. Each crawl
        runs independently and removes its own stale documents via delete_stale().
        The index is NOT pre-wiped — use the admin "Drop and recreate" operation
        when a full clean slate is required.
    """
    from flask_app.models.crawler_target import CrawlerTarget

    def _impl(db_session):
        targets = db_session.query(CrawlerTarget).all()
        results = []
        for target in targets:
            r = crawl_target.delay(target.id)
            results.append(r.id)
        return results

    if _db_session is not None:
        return _impl(_db_session)
    app, db = _build_app_context()
    with app.app_context():
        return _impl(db.session)


if __name__ == "__main__":
    pass
