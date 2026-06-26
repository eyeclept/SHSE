"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Admin health/status concern: the dashboard, the /_health HTMX poll, the
    OpenSearch index-operations page and its destructive/maintenance actions
    (wipe, full reindex, vectorize), and the dashboard-level bulk crawl/reindex/
    vectorize triggers. Registers its routes on the shared ``admin_bp``.
"""
# Imports
import logging

from flask import flash, redirect, render_template, request, url_for

from flask_app.routes.admin import admin_bp
from flask_app.routes.admin._shared import admin_required, _check_services

# Globals
logger = logging.getLogger(__name__)

_INDEX_NAME = "shse_pages"


# Functions
def _get_index_stats(client=None):
    """
    Input: optional OpenSearch client
    Output: dict {docs, services, last_crawl, vector_coverage_pct, ...}
    Details:
        Queries OpenSearch for aggregate statistics. Returns zeros on error.
        Cached in Redis with a short TTL (the admin dashboard reruns this sweep
        on every load); bypassed under TESTING and when a client is injected.
    """
    from flask_app.services.opensearch import get_client
    from flask_app.services.cache import cached_json, STATS_TTL

    def _compute():
        try:
            c = client or get_client()
            count = c.count(index=_INDEX_NAME).get("count", 0)
            agg_resp = c.search(index=_INDEX_NAME, body={
                "size": 0,
                "aggs": {
                    "svc": {"cardinality": {"field": "service_nickname"}},
                    "vectorized": {"filter": {"term": {"vectorized": True}}},
                },
            })
            aggs = agg_resp.get("aggregations", {})
            svc_count = aggs.get("svc", {}).get("value", 0)
            vec_count = aggs.get("vectorized", {}).get("doc_count", 0)
            last = c.search(index=_INDEX_NAME, body={
                "size": 1, "sort": [{"crawled_at": "desc"}], "_source": ["crawled_at"],
            })
            hits = last["hits"]["hits"]
            last_crawl = hits[0]["_source"].get("crawled_at", "")[:19] if hits else "—"
            pct = int(vec_count / count * 100) if count > 0 else 0
            return {
                "docs": count,
                "services": svc_count,
                "last_crawl": last_crawl,
                "vector_coverage_pct": pct,
                "queue_depth": 0,
                "indexed_24h": 0,
            }
        except Exception:
            logger.warning("OpenSearch unavailable — returning zero index stats", exc_info=True)
            return {
                "docs": 0, "services": 0, "last_crawl": "—",
                "vector_coverage_pct": 0, "queue_depth": 0, "indexed_24h": 0,
            }

    return cached_json("shse:stats:admin", STATS_TTL, _compute)


# ── Dashboard ──────────────────────────────────────────────────────────────

@admin_bp.route("/")
@admin_required
def index():
    """
    Input: None
    Output: rendered admin dashboard
    Details:
        Shows system health, index stats, and recent crawl activity.
    """
    from flask_app import db
    from flask_app.models.crawl_job import CrawlJob
    from flask_app.models.crawler_target import CrawlerTarget

    health = _check_services()
    stats = _get_index_stats()

    recent_jobs = (
        db.session.query(CrawlJob)
        .order_by(CrawlJob.started_at.desc())
        .limit(10)
        .all()
    )
    # Resolve target nicknames in one IN-clause query rather than per row.
    target_cache = {None: "—"}
    target_ids = {j.target_id for j in recent_jobs if j.target_id is not None}
    if target_ids:
        for t in db.session.query(CrawlerTarget).filter(CrawlerTarget.id.in_(target_ids)):
            target_cache[t.id] = t.nickname
    activity = []
    for job in recent_jobs:
        label = target_cache.get(job.target_id, "(deleted)")
        activity.append({
            "kind": "crawl",
            "label": label,
            "when": str(job.started_at)[:16] if job.started_at else "—",
            "status": "ok" if job.status == "success" else
                      "fail" if job.status == "failure" else "pending",
        })

    tls_warning = db.session.query(CrawlerTarget).filter_by(tls_verify=False).count() > 0

    return render_template(
        "admin/index.html",
        health=health,
        stats=stats,
        activity=activity,
        tls_warning=tls_warning,
    )


@admin_bp.route("/_health")
@admin_required
def health_partial():
    """
    Input: None
    Output: rendered _health_grid.html fragment (HTMX poll target)
    Details:
        Returns only the health grid HTML so the dashboard can poll every 5s
        without a full page reload.
    """
    health = _check_services()
    return render_template("admin/_health_grid.html", health=health)


# ── Bulk crawl / reindex / vectorize triggers (dashboard buttons) ───────────

@admin_bp.route("/crawl-all", methods=["POST"])
@admin_required
def crawl_all():
    """
    Input: None
    Output: redirect to jobs page
    """
    from celery_worker.tasks.crawl import crawl_all as celery_crawl_all
    try:
        celery_crawl_all.delay()
        flash("Crawl-all dispatched.", "success")
    except Exception:
        logger.warning("Task dispatch failed — Redis unreachable", exc_info=True)
        flash("Task queue unavailable — Redis is not reachable", "error")
    return redirect(url_for("admin.jobs"))


@admin_bp.route("/reindex-all", methods=["POST"])
@admin_required
def reindex_all():
    """
    Input: None
    Output: redirect to jobs page
    """
    from celery_worker.tasks.index import reindex_all as celery_reindex_all
    try:
        celery_reindex_all.delay()
        flash("Reindex-all dispatched.", "success")
    except Exception:
        logger.warning("Task dispatch failed — Redis unreachable", exc_info=True)
        flash("Task queue unavailable — Redis is not reachable", "error")
    return redirect(url_for("admin.jobs"))


@admin_bp.route("/vectorize", methods=["POST"])
@admin_required
def vectorize_pending():
    """
    Input: None
    Output: redirect to jobs page
    """
    from celery_worker.tasks.vectorize import vectorize_pending as celery_vec
    try:
        celery_vec.delay()
        flash("Vectorize dispatched.", "success")
    except Exception:
        logger.warning("Task dispatch failed — Redis unreachable", exc_info=True)
        flash("Task queue unavailable — Redis is not reachable", "error")
    return redirect(url_for("admin.jobs"))


# ── Index operations ───────────────────────────────────────────────────────

@admin_bp.route("/index")
@admin_required
def index_ops():
    """
    Input: None
    Output: rendered index operations page
    """
    from flask_app.services.opensearch import get_client
    health = _check_services()
    stats = _get_index_stats()
    try:
        client = get_client()
        idx_stats = client.indices.stats(index=_INDEX_NAME)
        store_mb = round(
            idx_stats["indices"].get(_INDEX_NAME, {})
            .get("total", {}).get("store", {}).get("size_in_bytes", 0) / 1e6, 1
        )
    except Exception:
        logger.warning("Failed to fetch OpenSearch store size", exc_info=True)
        store_mb = 0

    return render_template(
        "admin/index_ops.html",
        index_stats={
            "docs": stats["docs"],
            "vectorized": 0,
            "vector_coverage_pct": stats["vector_coverage_pct"],
            "shards": 1,
            "replicas": 0,
            "store_size_mb": store_mb,
            "last_modified": stats["last_crawl"],
        },
        opensearch_up=health.get("opensearch", {}).get("status") == "up",
        llm_api_up=health.get("llm_api", {}).get("status") == "up",
        running_jobs=[],
    )


@admin_bp.route("/index/reindex_all", methods=["POST"])
@admin_required
def reindex_all_from_index():
    """
    Input: None
    Output: redirect to index_ops page
    Details:
        Wipes the full OpenSearch index and re-crawls all targets.
    """
    from celery_worker.tasks.index import reindex_all as celery_reindex_all
    try:
        celery_reindex_all.delay()
        flash("Full reindex dispatched.", "success")
    except Exception:
        logger.warning("Task dispatch failed — Redis unreachable", exc_info=True)
        flash("Task queue unavailable — Redis is not reachable", "error")
    return redirect(url_for("admin.index_ops"))


@admin_bp.route("/index/vectorize_all", methods=["POST"])
@admin_required
def vectorize_all():
    """
    Input: None
    Output: redirect to index_ops page
    """
    from celery_worker.tasks.vectorize import vectorize_pending as celery_vec
    try:
        celery_vec.delay()
        flash("Vectorize-all dispatched.", "success")
    except Exception:
        logger.warning("Task dispatch failed — Redis unreachable", exc_info=True)
        flash("Task queue unavailable — Redis is not reachable", "error")
    return redirect(url_for("admin.index_ops"))


@admin_bp.route("/index/drop", methods=["POST"])
@admin_required
def wipe_index():
    """
    Input: confirm_text form field (must equal 'DROP')
    Output: redirect to index_ops page
    Details:
        Drops and recreates the OpenSearch index. Destructive operation.
    """
    from flask_app.services.opensearch import wipe_index as os_wipe, create_index

    if request.form.get("confirm_text") != "DROP":
        flash("Confirmation text incorrect — index not wiped.", "error")
        return redirect(url_for("admin.index_ops"))
    try:
        os_wipe()
        create_index()
        flash("Index wiped and recreated.", "success")
    except Exception as exc:
        logger.exception("Index wipe/recreate failed")
        flash(f"Wipe failed: {exc}", "error")
    return redirect(url_for("admin.index_ops"))
