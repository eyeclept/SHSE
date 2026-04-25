"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Crawl and harvest Celery tasks.
    crawl_target dispatches to the correct harvest function based on target type.
    crawl_all iterates all targets and fans out to crawl_target.
    scheduled_crawl is the Celery Beat entry point (dispatches by nickname).
    harvest_oai, harvest_feeds, push_api_content are type-specific stubs;
    real external integrations (Metha, feedparser, adapters) are wired here.
"""
# Imports
from datetime import datetime

from celery_worker.app import celery
from flask_app.services.nutch import trigger_crawl, fetch_results
from flask_app.services.opensearch import index_document, delete_stale

# Globals
_INDEX_NAME = "shse_pages"


# Functions
def _build_app_context():
    """
    Input: None
    Output: (Flask app, db) — used by tasks when no injected session
    Details:
        Deferred import avoids circular import at module load time.
    """
    from flask_app import create_app, db as _db
    return create_app(), _db


def _crawl_target_impl(target_id, db_session, nutch_session=None, os_client=None):
    """
    Input:
        target_id     - int, CrawlerTarget primary key
        db_session    - SQLAlchemy session
        nutch_session - optional requests.Session for Nutch (injectable for tests)
        os_client     - optional OpenSearch client (injectable for tests)
    Output:
        int — CrawlJob id of the created job
    Details:
        Creates a CrawlJob, routes to the correct harvest implementation, then
        updates the job status on success or failure.
    """
    from flask_app.models.crawler_target import CrawlerTarget
    from flask_app.models.crawl_job import CrawlJob

    target = db_session.get(CrawlerTarget, target_id)
    if target is None:
        raise ValueError(f"CrawlerTarget {target_id} not found")

    job = CrawlJob(
        target_id=target_id,
        status="started",
        started_at=datetime.utcnow(),
    )
    db_session.add(job)
    db_session.commit()

    try:
        if target.target_type in ("service", "network"):
            _nutch_crawl(target, nutch_session, os_client)
        elif target.target_type == "oai-pmh":
            _harvest_oai_impl(target, os_client)
        elif target.target_type == "feed":
            _harvest_feeds_impl(target, os_client)
        elif target.target_type == "api-push":
            _push_api_content_impl(target, os_client)
        job.status = "success"
        job.finished_at = datetime.utcnow()
    except Exception as exc:
        job.status = "failure"
        job.finished_at = datetime.utcnow()
        db_session.commit()
        raise exc

    db_session.commit()
    return job.id


def _nutch_crawl(target, nutch_session=None, os_client=None):
    """
    Input:
        target        - CrawlerTarget ORM object (type service or network)
        nutch_session - optional requests.Session for Nutch
        os_client     - optional OpenSearch client
    Output: None
    Details:
        Builds seed URLs from target config, triggers Nutch crawl pipeline,
        fetches result node metadata, and indexes each URL to OpenSearch.
        Page text is not returned by the Nutch REST API; the URL is stored as
        placeholder text pending a segment-parse integration.
    """
    nickname = target.nickname or target.network or str(target.id)

    if target.target_type == "service":
        protocol = target.service or "http"
        port = target.port or 80
        route = target.route or "/"
        seed_urls = [f"{protocol}://{target.url}:{port}{route}"]
    else:
        seed_urls = [target.network]

    run_start = datetime.utcnow().isoformat()
    crawl_id = trigger_crawl(
        seed_urls,
        tls_verify=bool(target.tls_verify),
        session=nutch_session,
    )
    results = fetch_results(crawl_id, session=nutch_session)

    for node in results.get("nodes", []):
        url = node.get("url", "")
        index_document(
            url=url,
            port=target.port or 80,
            title=url,
            crawled_at=datetime.utcnow().isoformat(),
            service_nickname=nickname,
            content_type="text/html",
            text=url,  # placeholder: full text requires Nutch segment parsing
            source_type="nutch",
            client=os_client,
        )

    delete_stale(nickname, run_start, client=os_client)


def _harvest_oai_impl(target, os_client=None, _docs=None):
    """
    Input:
        target    - CrawlerTarget ORM object (type oai-pmh)
        os_client - optional OpenSearch client
        _docs     - injectable doc list for tests; production path uses []
    Output: None
    Details:
        Stub for Metha OAI-PMH harvest. Real integration calls:
            metha-sync -format oai_dc {target.url}{target.endpoint}
        then parses ListRecords XML and indexes each record.
        Indexes any provided records with source_type="oai-pmh".
    """
    nickname = target.nickname or str(target.id)
    run_start = datetime.utcnow().isoformat()
    docs = _docs if _docs is not None else []

    for doc in docs:
        index_document(
            url=doc["url"],
            port=80,
            title=doc.get("title", ""),
            crawled_at=datetime.utcnow().isoformat(),
            service_nickname=nickname,
            content_type="text/xml",
            text=doc["text"],
            source_type="oai-pmh",
            client=os_client,
        )

    delete_stale(nickname, run_start, client=os_client)


def _harvest_feeds_impl(target, os_client=None, _docs=None):
    """
    Input:
        target    - CrawlerTarget ORM object (type feed)
        os_client - optional OpenSearch client
        _docs     - injectable doc list for tests; production path uses []
    Output: None
    Details:
        Stub for RSS/Atom/ActivityPub feed harvest. Real integration parses
        {target.url}{target.feed_path} with feedparser and indexes each entry.
        Indexes any parsed entries with source_type="rss".
    """
    nickname = target.nickname or str(target.id)
    run_start = datetime.utcnow().isoformat()
    docs = _docs if _docs is not None else []

    for doc in docs:
        index_document(
            url=doc["url"],
            port=80,
            title=doc.get("title", ""),
            crawled_at=datetime.utcnow().isoformat(),
            service_nickname=nickname,
            content_type="application/rss+xml",
            text=doc["text"],
            source_type="rss",
            client=os_client,
        )

    delete_stale(nickname, run_start, client=os_client)


def _push_api_content_impl(target, os_client=None, _docs=None):
    """
    Input:
        target    - CrawlerTarget ORM object (type api-push)
        os_client - optional OpenSearch client
        _docs     - injectable doc list for tests; production path uses []
    Output: None
    Details:
        Stub for custom adapter-based API harvest. Real integration imports
        the adapter module named in target.adapter and calls its fetch() function.
        Indexes any returned documents with source_type="api-push".
    """
    nickname = target.nickname or str(target.id)
    run_start = datetime.utcnow().isoformat()
    docs = _docs if _docs is not None else []

    for doc in docs:
        index_document(
            url=doc["url"],
            port=80,
            title=doc.get("title", ""),
            crawled_at=datetime.utcnow().isoformat(),
            service_nickname=nickname,
            content_type="application/json",
            text=doc["text"],
            source_type="api-push",
            client=os_client,
        )

    delete_stale(nickname, run_start, client=os_client)


@celery.task
def crawl_target(target_id, _db_session=None, _nutch_session=None, _os_client=None):
    """
    Input:
        target_id      - int, CrawlerTarget primary key
        _db_session    - injectable SQLAlchemy session (tests only)
        _nutch_session - injectable requests.Session for Nutch (tests only)
        _os_client     - injectable OpenSearch client (tests only)
    Output: int — CrawlJob id
    Details:
        Creates a CrawlJob row, routes to the appropriate harvest function based
        on target_type, and updates the job status on completion.
    """
    if _db_session is not None:
        return _crawl_target_impl(target_id, _db_session, _nutch_session, _os_client)
    app, db = _build_app_context()
    with app.app_context():
        return _crawl_target_impl(target_id, db.session, _nutch_session, _os_client)


@celery.task
def crawl_all(_db_session=None):
    """
    Input:
        _db_session - injectable SQLAlchemy session (tests only)
    Output: list[str] — Celery AsyncResult IDs of dispatched crawl_target tasks
    Details:
        Queries all CrawlerTarget rows and dispatches crawl_target.delay() for each.
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


@celery.task
def scheduled_crawl(nickname, _db_session=None, _nutch_session=None, _os_client=None):
    """
    Input:
        nickname       - str, the target's nickname (used as Beat schedule key)
        _db_session    - injectable SQLAlchemy session (tests only)
        _nutch_session - injectable requests.Session for Nutch (tests only)
        _os_client     - injectable OpenSearch client (tests only)
    Output: int — CrawlJob id, or None if no target found
    Details:
        Celery Beat entry point. Looks up the target by nickname and
        calls _crawl_target_impl directly (avoiding a second task dispatch).
    """
    from flask_app.models.crawler_target import CrawlerTarget

    def _impl(db_session):
        target = db_session.query(CrawlerTarget).filter_by(nickname=nickname).first()
        if target is None:
            return None
        return _crawl_target_impl(target.id, db_session, _nutch_session, _os_client)

    if _db_session is not None:
        return _impl(_db_session)
    app, db = _build_app_context()
    with app.app_context():
        return _impl(db.session)


@celery.task
def harvest_oai(target_id, _db_session=None, _os_client=None):
    """
    Input:
        target_id   - int, CrawlerTarget primary key (must have type oai-pmh)
        _db_session - injectable SQLAlchemy session (tests only)
        _os_client  - injectable OpenSearch client (tests only)
    Output: int — CrawlJob id
    Details:
        Standalone entry point for OAI-PMH harvest. Delegates to crawl_target
        so that a CrawlJob row is created and the status lifecycle is tracked.
    """
    return crawl_target(target_id, _db_session=_db_session, _os_client=_os_client)


@celery.task
def harvest_feeds(target_id, _db_session=None, _os_client=None):
    """
    Input:
        target_id   - int, CrawlerTarget primary key (must have type feed)
        _db_session - injectable SQLAlchemy session (tests only)
        _os_client  - injectable OpenSearch client (tests only)
    Output: int — CrawlJob id
    Details:
        Standalone entry point for feed harvest. Delegates to crawl_target
        so that a CrawlJob row is created and the status lifecycle is tracked.
    """
    return crawl_target(target_id, _db_session=_db_session, _os_client=_os_client)


@celery.task
def push_api_content(target_id, _db_session=None, _os_client=None):
    """
    Input:
        target_id   - int, CrawlerTarget primary key (must have type api-push)
        _db_session - injectable SQLAlchemy session (tests only)
        _os_client  - injectable OpenSearch client (tests only)
    Output: int — CrawlJob id
    Details:
        Standalone entry point for api-push harvest. Delegates to crawl_target
        so that a CrawlJob row is created and the status lifecycle is tracked.
    """
    return crawl_target(target_id, _db_session=_db_session, _os_client=_os_client)


if __name__ == "__main__":
    pass
