"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Reindex Celery tasks. Delete existing OpenSearch docs for a target or
    for the entire index, then re-crawl to rebuild from scratch.
"""
# Imports
from celery.utils.log import get_task_logger
from celery_worker.app import celery
from celery_worker.tasks.crawl import _crawl_target_impl, crawl_target
from flask_app.services.opensearch import delete_by_nickname, wipe_index

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
    Output: int — CrawlJob id from the subsequent crawl_target call
    Details:
        Deletes all OpenSearch documents for the target's service_nickname,
        then triggers a fresh crawl via crawl_target.
    """
    from flask_app.models.crawler_target import CrawlerTarget

    def _impl(db_session):
        target = db_session.get(CrawlerTarget, target_id)
        if target is None:
            raise ValueError(f"CrawlerTarget {target_id} not found")
        nickname = target.nickname or target.network or str(target.id)
        delete_by_nickname(nickname, client=_os_client)
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
        Wipes the entire OpenSearch index, then dispatches crawl_target.delay()
        for every CrawlerTarget row.
    """
    from flask_app.models.crawler_target import CrawlerTarget

    def _impl(db_session):
        wipe_index(client=_os_client)
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
