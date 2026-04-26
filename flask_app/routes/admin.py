"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Admin blueprint. Provides crawl management, index controls, job status,
    system health indicators, and crawler config editing.
    All routes require admin role; enforced by @admin_required.
"""
# Imports
import time
from datetime import datetime, timedelta
from functools import wraps

import requests as _requests
from flask import (
    Blueprint, abort, flash, redirect, render_template,
    request, url_for,
)
from flask_login import current_user
from sqlalchemy import text

# Globals
admin_bp = Blueprint("admin", __name__)

_INDEX_NAME = "shse_pages"
_PROBE_TIMEOUT = 3   # seconds per health probe


# Functions
def admin_required(f):
    """
    Input: view function
    Output: decorated view function
    Details:
        Redirects unauthenticated users to login.
        Returns 403 for authenticated non-admin users.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if current_user.role != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated


def _check_services():
    """
    Input: None
    Output: dict {service: {status, latency_ms, message}}
    Details:
        Probes OpenSearch, Nutch, LLM API, Redis, and MariaDB with short
        timeouts. Returns 'up', 'down', or 'degraded' per service.
        All exceptions are caught so a single unreachable service never
        prevents the dashboard from rendering.
    """
    from flask_app.services.opensearch import get_client as os_client
    from flask_app.config import Config
    from flask_app import db

    results = {}

    # OpenSearch
    try:
        t0 = time.monotonic()
        client = os_client()
        health = client.cluster.health()
        ms = int((time.monotonic() - t0) * 1000)
        status_map = {"green": "up", "yellow": "degraded", "red": "down"}
        results["opensearch"] = {
            "status": status_map.get(health.get("status", "red"), "down"),
            "latency_ms": ms,
            "message": None,
        }
    except Exception as exc:
        results["opensearch"] = {"status": "down", "latency_ms": None, "message": str(exc)[:80]}

    # Nutch
    try:
        t0 = time.monotonic()
        nutch_host = Config.NUTCH_HOST
        nutch_port = Config.NUTCH_PORT
        resp = _requests.get(
            f"http://{nutch_host}:{nutch_port}/admin/",
            timeout=_PROBE_TIMEOUT,
        )
        ms = int((time.monotonic() - t0) * 1000)
        results["nutch"] = {
            "status": "up" if resp.ok else "degraded",
            "latency_ms": ms,
            "message": None if resp.ok else f"HTTP {resp.status_code}",
        }
    except Exception as exc:
        results["nutch"] = {"status": "down", "latency_ms": None, "message": str(exc)[:80]}

    # LLM API
    try:
        t0 = time.monotonic()
        llm_base = Config.LLM_API_BASE.rstrip("/")
        resp = _requests.get(f"{llm_base}/models", timeout=_PROBE_TIMEOUT)
        ms = int((time.monotonic() - t0) * 1000)
        results["llm_api"] = {
            "status": "up" if resp.ok else "degraded",
            "latency_ms": ms,
            "message": None if resp.ok else f"HTTP {resp.status_code}",
        }
    except Exception as exc:
        results["llm_api"] = {"status": "down", "latency_ms": None, "message": str(exc)[:80]}

    # Redis
    try:
        import redis as _redis
        t0 = time.monotonic()
        r = _redis.Redis(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            socket_connect_timeout=_PROBE_TIMEOUT,
        )
        r.ping()
        ms = int((time.monotonic() - t0) * 1000)
        results["redis"] = {"status": "up", "latency_ms": ms, "message": None}
    except Exception as exc:
        results["redis"] = {"status": "down", "latency_ms": None, "message": str(exc)[:80]}

    # MariaDB
    try:
        t0 = time.monotonic()
        db.session.execute(text("SELECT 1"))
        ms = int((time.monotonic() - t0) * 1000)
        results["mariadb"] = {"status": "up", "latency_ms": ms, "message": None}
    except Exception as exc:
        results["mariadb"] = {"status": "down", "latency_ms": None, "message": str(exc)[:80]}

    return results


def _get_index_stats(client=None):
    """
    Input: optional OpenSearch client
    Output: dict {docs, services, last_crawl, vector_coverage_pct, ...}
    Details:
        Queries OpenSearch for aggregate statistics. Returns zeros on error.
    """
    from flask_app.services.opensearch import get_client
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
        return {
            "docs": 0, "services": 0, "last_crawl": "—",
            "vector_coverage_pct": 0, "queue_depth": 0, "indexed_24h": 0,
        }


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
    target_cache = {}
    activity = []
    for job in recent_jobs:
        if job.target_id not in target_cache:
            t = db.session.get(CrawlerTarget, job.target_id)
            target_cache[job.target_id] = t.nickname if t else "(deleted)"
        label = target_cache[job.target_id]
        activity.append({
            "kind": "crawl",
            "label": label,
            "when": str(job.started_at)[:16] if job.started_at else "—",
            "status": "ok" if job.status == "success" else
                      "fail" if job.status == "failure" else "pending",
        })

    return render_template(
        "admin/index.html",
        health=health,
        stats=stats,
        activity=activity,
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


# ── Targets ────────────────────────────────────────────────────────────────

@admin_bp.route("/targets")
@admin_required
def targets():
    """
    Input: None
    Output: rendered targets list page
    Details:
        Lists all crawler targets. Passes service health flags so the template
        can disable action buttons when a service is unreachable.
    """
    from flask_app import db
    from flask_app.models.crawler_target import CrawlerTarget

    health = _check_services()
    all_targets = db.session.query(CrawlerTarget).order_by(CrawlerTarget.id).all()
    target_list = []
    for t in all_targets:
        target_list.append({
            "id": t.id,
            "name": t.nickname or t.network or str(t.id),
            "url": t.url or t.network or "—",
            "service_label": t.target_type,
            "enabled": True,
            "last_crawl": "—",
            "next_crawl": "—",
            "doc_count": 0,
            "status": "idle",
        })

    return render_template(
        "admin/targets.html",
        targets=target_list,
        opensearch_up=health.get("opensearch", {}).get("status") == "up",
        nutch_up=health.get("nutch", {}).get("status") == "up",
        llm_api_up=health.get("llm_api", {}).get("status") == "up",
    )


@admin_bp.route("/targets/<int:target_id>/crawl", methods=["POST"])
@admin_required
def crawl_target(target_id):
    """
    Input: target_id (URL param)
    Output: redirect to jobs page
    Details:
        Dispatches crawl_target Celery task.
    """
    from celery_worker.tasks.crawl import crawl_target as celery_crawl
    celery_crawl.delay(target_id)
    flash(f"Crawl dispatched for target {target_id}.", "success")
    return redirect(url_for("admin.jobs"))


@admin_bp.route("/targets/<int:target_id>/reindex", methods=["POST"])
@admin_required
def reindex_target(target_id):
    """
    Input: target_id (URL param)
    Output: redirect to jobs page
    Details:
        Dispatches reindex_target Celery task.
    """
    from celery_worker.tasks.index import reindex_target as celery_reindex
    celery_reindex.delay(target_id)
    flash(f"Reindex dispatched for target {target_id}.", "success")
    return redirect(url_for("admin.jobs"))


@admin_bp.route("/crawl-all", methods=["POST"])
@admin_required
def crawl_all():
    """
    Input: None
    Output: redirect to jobs page
    """
    from celery_worker.tasks.crawl import crawl_all as celery_crawl_all
    celery_crawl_all.delay()
    flash("Crawl-all dispatched.", "success")
    return redirect(url_for("admin.jobs"))


@admin_bp.route("/reindex-all", methods=["POST"])
@admin_required
def reindex_all():
    """
    Input: None
    Output: redirect to jobs page
    """
    from celery_worker.tasks.index import reindex_all as celery_reindex_all
    celery_reindex_all.delay()
    flash("Reindex-all dispatched.", "success")
    return redirect(url_for("admin.jobs"))


@admin_bp.route("/vectorize", methods=["POST"])
@admin_required
def vectorize_pending():
    """
    Input: None
    Output: redirect to jobs page
    """
    from celery_worker.tasks.vectorize import vectorize_pending as celery_vec
    celery_vec.delay()
    flash("Vectorize dispatched.", "success")
    return redirect(url_for("admin.jobs"))


# ── Jobs ───────────────────────────────────────────────────────────────────

def _job_rows(status_filter="all"):
    """
    Input: status_filter str ('all' or a specific status)
    Output: list of job dicts for the jobs template
    """
    from flask_app import db
    from flask_app.models.crawl_job import CrawlJob
    from flask_app.models.crawler_target import CrawlerTarget

    q = db.session.query(CrawlJob).order_by(CrawlJob.started_at.desc()).limit(100)
    if status_filter != "all":
        q = q.filter(CrawlJob.status == status_filter)

    target_cache = {}
    rows = []
    for job in q.all():
        if job.target_id not in target_cache:
            t = db.session.get(CrawlerTarget, job.target_id)
            target_cache[job.target_id] = t.nickname if t else "(deleted)"
        duration = None
        if job.started_at and job.finished_at:
            duration = str(job.finished_at - job.started_at).split(".")[0]
        rows.append({
            "id": job.id,
            "kind": "crawl",
            "target": target_cache[job.target_id],
            "status": job.status or "unknown",
            "progress": 100 if job.status in ("success", "failure") else 0,
            "started_at": str(job.started_at)[:16] if job.started_at else "—",
            "finished_at": str(job.finished_at)[:16] if job.finished_at else "—",
            "took": duration,
            "message": None,
        })
    return rows


@admin_bp.route("/jobs")
@admin_required
def jobs():
    """
    Input: ?status= filter (optional)
    Output: rendered jobs page
    """
    from flask_app import db
    from flask_app.models.crawl_job import CrawlJob

    status_filter = request.args.get("status", "all")
    counts = {s: db.session.query(CrawlJob).filter_by(status=s).count()
              for s in ("started", "success", "failure")}
    counts["all"] = sum(counts.values())
    return render_template(
        "admin/jobs.html",
        jobs=_job_rows(status_filter),
        filter=status_filter,
        counts=counts,
    )


@admin_bp.route("/jobs/_table")
@admin_required
def jobs_table():
    """
    Input: ?status= filter (optional)
    Output: rendered _jobs_rows.html fragment (HTMX poll target)
    """
    from flask_app import db
    from flask_app.models.crawl_job import CrawlJob

    status_filter = request.args.get("status", "all")
    counts = {s: db.session.query(CrawlJob).filter_by(status=s).count()
              for s in ("started", "success", "failure")}
    counts["all"] = sum(counts.values())
    return render_template(
        "admin/_jobs_rows.html",
        jobs=_job_rows(status_filter),
        filter=status_filter,
        counts=counts,
    )


# ── Config ─────────────────────────────────────────────────────────────────

@admin_bp.route("/config", methods=["GET", "POST"])
@admin_required
def crawler_config():
    """
    Input: yaml_config (textarea POST or file upload)
    Output: rendered config editor; on POST parses and persists
    """
    from flask_app import db
    from flask_app.config_parser import parse_config, persist_targets
    from flask_app.models.crawler_target import CrawlerTarget

    yaml_text = ""
    validation = None

    # Pre-fill with the first target's yaml_source if available
    existing = db.session.query(CrawlerTarget).first()
    if existing and existing.yaml_source:
        yaml_text = existing.yaml_source

    if request.method == "POST":
        uploaded = request.files.get("upload")
        if uploaded and uploaded.filename:
            yaml_text = uploaded.read().decode("utf-8", errors="replace")
        else:
            yaml_text = request.form.get("yaml", "").strip()

        try:
            parsed = parse_config(yaml_text)
            persist_targets(yaml_text, parsed, db.session)
            validation = {"ok": True, "errors": [], "warnings": []}
            flash(f"Config saved — {len(parsed)} target(s) loaded.", "success")
        except Exception as exc:
            validation = {"ok": False, "errors": [{"line": None, "message": str(exc)}], "warnings": []}
            flash("YAML parse failed — see errors below.", "error")

    return render_template(
        "admin/config.html",
        yaml_text=yaml_text,
        validation=validation,
        last_saved="—",
    )


@admin_bp.route("/config/_validate", methods=["POST"])
@admin_required
def config_validate():
    """
    Input: yaml= form field (HTMX debounced request)
    Output: rendered _yaml_validation.html fragment
    """
    from flask_app.config_parser import parse_config

    yaml_text = request.form.get("yaml", "")
    try:
        parsed = parse_config(yaml_text)
        validation = {
            "ok": True,
            "errors": [],
            "warnings": [f"{len(parsed)} target(s) parsed."],
        }
    except Exception as exc:
        validation = {
            "ok": False,
            "errors": [{"line": None, "message": str(exc)}],
            "warnings": [],
        }
    return render_template("admin/_yaml_validation.html", validation=validation)


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
    celery_reindex_all.delay()
    flash("Full reindex dispatched.", "success")
    return redirect(url_for("admin.index_ops"))


@admin_bp.route("/index/vectorize_all", methods=["POST"])
@admin_required
def vectorize_all():
    """
    Input: None
    Output: redirect to index_ops page
    """
    from celery_worker.tasks.vectorize import vectorize_pending as celery_vec
    celery_vec.delay()
    flash("Vectorize-all dispatched.", "success")
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
        flash(f"Wipe failed: {exc}", "error")
    return redirect(url_for("admin.index_ops"))


if __name__ == "__main__":
    pass
