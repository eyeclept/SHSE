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

from celery.utils.log import get_task_logger
from celery_worker.app import celery
from flask_app.services.nutch import _discover_urls, _fetch_page_text
from flask_app.services.opensearch import index_document, delete_stale

# Globals
_INDEX_NAME = "shse_pages"
logger = get_task_logger(__name__)


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
    logger.info("CrawlJob %s started — target_id=%s task_id=%s", job.id, target_id, job.task_id)

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
        job.message = None
        logger.info("CrawlJob %s success — target_id=%s", job.id, target_id)
    except Exception as exc:
        job.status = "failure"
        job.finished_at = datetime.utcnow()
        job.message = str(exc)[:500]
        logger.exception("CrawlJob %s failure — target_id=%s", job.id, target_id)
        db_session.commit()
        raise exc

    db_session.commit()

    # Auto-trigger vectorization after a successful crawl when LLM is configured.
    # Runs as a separate Celery task so it doesn't block or fail the crawl status.
    try:
        from flask_app.config import Config
        if Config.LLM_API_BASE:
            from celery_worker.tasks.vectorize import vectorize_pending
            vectorize_pending.delay()
    except Exception:
        logger.warning("Failed to dispatch vectorize_pending after crawl job %s", job.id, exc_info=True)

    return job.id


def _nutch_crawl(target, nutch_session=None, os_client=None):
    """
    Input:
        target        - CrawlerTarget ORM object (type service or network)
        nutch_session - unused; kept for signature compatibility with tests
        os_client     - optional OpenSearch client
    Output: None
    Details:
        BFS-crawls the target starting from the seed URL, discovers all
        same-host pages up to max_depth=2, fetches each page's text, and
        indexes it to OpenSearch. Nutch is not used for URL discovery;
        _discover_urls handles link extraction directly so no Nutch PARSE
        step is required.
    """
    nickname = target.nickname or target.network or str(target.id)
    tls_ok = bool(target.tls_verify)
    run_start = datetime.utcnow().isoformat()

    if target.target_type == "service":
        protocol = target.service or "http"
        port = target.port or 80
        route = target.route or "/"
        seed_url = f"{protocol}://{target.url}:{port}{route}"
    else:
        seed_url = target.network or ""

    if not seed_url:
        return

    depth = target.crawl_depth if target.crawl_depth is not None else 2
    urls = _discover_urls(seed_url, tls_verify=tls_ok, max_depth=depth)
    if not urls:
        raise RuntimeError(
            f"_discover_urls returned no reachable URLs from seed {seed_url!r} — "
            "check network connectivity between the crawler and the target host "
            "(e.g. Docker cannot reach the target network)"
        )
    logger.info("_nutch_crawl: discovered %d URL(s) from seed %s", len(urls), seed_url)

    documents_indexed = 0
    for url in urls:
        page_text = _fetch_page_text(url, tls_verify=tls_ok)
        if not page_text or page_text == url:
            logger.warning("_nutch_crawl: skipping %s — no text extracted", url)
            continue
        index_document(
            url=url,
            port=target.port or 80,
            title=url,
            crawled_at=datetime.utcnow().isoformat(),
            service_nickname=nickname,
            content_type="text/html",
            text=page_text,
            source_type="nutch",
            client=os_client,
        )
        documents_indexed += 1

    if documents_indexed == 0:
        raise RuntimeError(
            f"_nutch_crawl indexed 0 documents from {len(urls)} discovered URL(s) "
            f"(seed {seed_url!r}) — all pages returned no extractable text"
        )
    logger.info("_nutch_crawl: indexed %d document(s) for target '%s'", documents_indexed, nickname)

    delete_stale(nickname, run_start, client=os_client)


def _oai_fetch(base_url, endpoint, resumption_token=None):
    """
    Input:
        base_url         - str, OAI-PMH repository base URL
        endpoint         - str, OAI endpoint path (e.g. /oai2d)
        resumption_token - str|None, pagination token from previous response
    Output:
        tuple (records, next_token) where records = list[{url, title, text}]
        and next_token = str|None
    Details:
        Makes a direct HTTP GET to the OAI-PMH ListRecords endpoint.
        Parses Dublin Core (oai_dc) records with stdlib xml.etree.ElementTree.
        Follows resumption tokens for paginated repositories.
    """
    import xml.etree.ElementTree as ET
    import urllib.parse
    import requests as _req

    _NS = {
        "oai": "http://www.openarchives.org/OAI/2.0/",
        "dc":  "http://purl.org/dc/elements/1.1/",
        "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
    }

    params = {"verb": "ListRecords"}
    if resumption_token:
        params["resumptionToken"] = resumption_token
    else:
        params["metadataPrefix"] = "oai_dc"

    url = base_url.rstrip("/") + endpoint
    try:
        resp = _req.get(url, params=params, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception:
        logger.warning("_oai_fetch failed for %s", url, exc_info=True)
        return [], None

    records = []
    for record in root.findall(".//oai:record", _NS):
        header = record.find("oai:header", _NS)
        metadata = record.find(".//oai_dc:dc", _NS)
        if header is None or metadata is None:
            continue
        identifier = (header.findtext("oai:identifier", default="", namespaces=_NS) or "").strip()
        title_el = metadata.find("dc:title", _NS)
        title = (title_el.text or "").strip() if title_el is not None else ""
        desc_el = metadata.find("dc:description", _NS)
        description = (desc_el.text or "").strip() if desc_el is not None else ""
        rec_url = f"{url}?verb=GetRecord&metadataPrefix=oai_dc&identifier={urllib.parse.quote(identifier)}"
        text = f"{title} {description}".strip() or identifier
        records.append({"url": rec_url, "title": title, "text": text})

    token_el = root.find(".//oai:resumptionToken", _NS)
    next_token = (token_el.text or "").strip() if token_el is not None else None

    return records, next_token or None


def _harvest_oai_impl(target, os_client=None, _docs=None):
    """
    Input:
        target    - CrawlerTarget ORM object (type oai-pmh)
        os_client - optional OpenSearch client
        _docs     - injectable doc list for tests; None uses real OAI-PMH fetch
    Output: None
    Details:
        Fetches records via OAI-PMH ListRecords (oai_dc format), following
        resumption tokens. Indexes each record with source_type="oai-pmh".
    """
    nickname = target.nickname or str(target.id)
    run_start = datetime.utcnow().isoformat()

    if _docs is not None:
        docs = _docs
    else:
        docs = []
        token = None
        while True:
            batch, token = _oai_fetch(target.url or "", target.endpoint or "/oai2d", token)
            docs.extend(batch)
            if not token:
                break

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


def _feed_fetch(base_url, feed_path):
    """
    Input:
        base_url  - str, site base URL
        feed_path - str, feed path (e.g. /rss, /feed.atom)
    Output:
        list[{url, title, text}] — one entry per feed item
    Details:
        Fetches the RSS/Atom feed with stdlib urllib.request and parses with
        xml.etree.ElementTree. Handles both RSS 2.0 and Atom 1.0 formats.
    """
    import xml.etree.ElementTree as ET
    import urllib.request

    _ATOM = "http://www.w3.org/2005/Atom"
    feed_url = base_url.rstrip("/") + feed_path

    try:
        with urllib.request.urlopen(feed_url, timeout=15) as resp:
            content = resp.read()
        root = ET.fromstring(content)
    except Exception:
        logger.warning("_feed_fetch failed for %s", feed_url, exc_info=True)
        return []

    docs = []
    # RSS 2.0
    for item in root.findall(".//item"):
        link = (item.findtext("link") or "").strip()
        title = (item.findtext("title") or "").strip()
        desc = (item.findtext("description") or "").strip()
        if link:
            docs.append({"url": link, "title": title, "text": f"{title} {desc}".strip() or link})

    # Atom 1.0
    for entry in root.findall(f"{{{_ATOM}}}entry"):
        link_el = entry.find(f"{{{_ATOM}}}link")
        link = (link_el.get("href", "") if link_el is not None else "").strip()
        title = (entry.findtext(f"{{{_ATOM}}}title") or "").strip()
        summary = (entry.findtext(f"{{{_ATOM}}}summary") or "").strip()
        content_el = entry.find(f"{{{_ATOM}}}content")
        body = (content_el.text or "").strip() if content_el is not None else ""
        text = f"{title} {summary} {body}".strip() or link
        if link:
            docs.append({"url": link, "title": title, "text": text})

    return docs


def _harvest_feeds_impl(target, os_client=None, _docs=None):
    """
    Input:
        target    - CrawlerTarget ORM object (type feed)
        os_client - optional OpenSearch client
        _docs     - injectable doc list for tests; None uses real feed fetch
    Output: None
    Details:
        Fetches RSS 2.0 or Atom 1.0 feed at {target.url}{target.feed_path}
        using stdlib urllib and indexes each entry with source_type="rss".
    """
    nickname = target.nickname or str(target.id)
    run_start = datetime.utcnow().isoformat()

    if _docs is not None:
        docs = _docs
    else:
        docs = _feed_fetch(target.url or "", target.feed_path or "/rss")

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
        _docs     - injectable doc list for tests; None uses real adapter fetch
    Output: None
    Details:
        Dynamically imports flask_app.adapters.{target.adapter} and calls
        its fetch(target) function. The adapter returns a list of
        {url, title, text} dicts. Each doc is indexed with source_type="api-push".
        Import errors and fetch failures are swallowed — the task does not fail
        because of a missing or broken adapter.
    """
    nickname = target.nickname or str(target.id)
    run_start = datetime.utcnow().isoformat()

    if _docs is not None:
        docs = _docs
    else:
        docs = []
        adapter_name = target.adapter or ""
        if adapter_name:
            try:
                import importlib
                mod = importlib.import_module(f"flask_app.adapters.{adapter_name}")
                docs = mod.fetch(target)
            except Exception:
                logger.exception(
                    "_push_api_content_impl: adapter '%s' failed for target %s",
                    adapter_name, target.nickname or target.id,
                )

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


@celery.task(autoretry_for=(Exception,), max_retries=3, countdown=30)
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
            logger.warning("scheduled_crawl: no target found for nickname '%s' — skipping", nickname)
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
