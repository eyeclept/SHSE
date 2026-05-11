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
import logging
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
logger = logging.getLogger(__name__)

_INDEX_NAME = "shse_pages"
_PROBE_TIMEOUT = 3   # seconds per health probe


# Functions
def _upsert_setting(db_session, key, value):
    from flask_app.models.system_setting import SystemSetting
    row = db_session.get(SystemSetting, key)
    if row is None:
        db_session.add(SystemSetting(key=key, value=value))
    else:
        row.value = value


def _validate_llm_model(model_name):
    """
    Input:  model_name — str to look for in the LLM API's model list
    Output: None if valid (or API unreachable); error string if model not found
    """
    from flask_app.config import Config
    if not Config.LLM_API_BASE:
        return None
    try:
        resp = _requests.get(
            f"{Config.LLM_API_BASE}/models", timeout=_PROBE_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()
        models = [m.get("id") or m.get("name", "") for m in data.get("models", data.get("data", []))]
        if model_name not in models:
            available = ", ".join(models[:10]) or "(none)"
            return f"Model '{model_name}' not found. Available: {available}"
    except Exception:
        logger.warning("_validate_llm_model: LLM API unreachable, skipping validation", exc_info=True)
    return None


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

    # TODO: these should be threaded, they don't need to be in sequence

    # OpenSearch
    try:
        t0 = time.monotonic()
        client = os_client()
        health = client.cluster.health()
        ms = int((time.monotonic() - t0) * 1000)
        status_map = {"green": "up", "yellow": "degraded", "red": "down"}
        os_status = status_map.get(health.get("status", "red"), "down")
        num_nodes = health.get("number_of_nodes", 1)
        unassigned = health.get("unassigned_shards", 0)
        relocating = health.get("relocating_shards", 0)
        detail = None
        if os_status == "degraded":
            parts = []
            if unassigned:
                note = " — replica shards cannot be placed on a single-node cluster (harmless)" if num_nodes == 1 else ""
                parts.append(f"{unassigned} unassigned shard(s){note}")
            if relocating:
                parts.append(f"{relocating} relocating shard(s)")
            detail = "; ".join(parts) if parts else "cluster status yellow"
        elif os_status == "down":
            detail = f"cluster status red — {unassigned} unassigned shard(s)"
        results["opensearch"] = {
            "status": os_status,
            "latency_ms": ms,
            "message": detail,
        }
    except Exception as exc:
        logger.warning("OpenSearch probe failed", exc_info=True)
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
        _exc = str(exc)
        if "Max retries" in _exc or "Connection refused" in _exc:
            logger.warning("Nutch REST server unreachable — reporting disabled", exc_info=True)
            results["nutch"] = {"status": "disabled", "latency_ms": None, "message": "REST server not running in this image"}
        else:
            logger.warning("Nutch probe failed", exc_info=True)
            results["nutch"] = {"status": "down", "latency_ms": None, "message": _exc[:80]}

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
        logger.warning("LLM API probe failed", exc_info=True)
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
        logger.warning("Redis probe failed", exc_info=True)
        results["redis"] = {"status": "down", "latency_ms": None, "message": str(exc)[:80]}

    # Celery workers (broadcast ping via Redis broker)
    try:
        from celery_worker.app import celery as _celery
        t0 = time.monotonic()
        inspector = _celery.control.inspect(timeout=_PROBE_TIMEOUT)
        active = inspector.ping()
        ms = int((time.monotonic() - t0) * 1000)
        if active:
            worker_count = len(active)
            results["celery"] = {
                "status": "up",
                "latency_ms": ms,
                "message": f"{worker_count} worker(s) responding",
            }
        else:
            results["celery"] = {"status": "down", "latency_ms": ms, "message": "No workers responded"}
    except Exception as exc:
        logger.warning("Celery probe failed", exc_info=True)
        results["celery"] = {"status": "down", "latency_ms": None, "message": str(exc)[:80]}

    # MariaDB
    try:
        t0 = time.monotonic()
        db.session.execute(text("SELECT 1"))
        ms = int((time.monotonic() - t0) * 1000)
        results["mariadb"] = {"status": "up", "latency_ms": ms, "message": None}
    except Exception as exc:
        logger.warning("MariaDB probe failed", exc_info=True)
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
        logger.warning("OpenSearch unavailable — returning zero index stats", exc_info=True)
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


# ── Targets ────────────────────────────────────────────────────────────────

def _target_to_dict(t):
    """Convert a CrawlerTarget ORM row to a plain dict for templates."""
    import yaml as _yaml
    sched = {}
    if t.schedule_yaml:
        try:
            sched = _yaml.safe_load(t.schedule_yaml) or {}
        except Exception:
            logger.warning("_target_to_dict: malformed schedule_yaml for target %s", t.id, exc_info=True)
    return {
        "id": t.id,
        "target_type": t.target_type,
        "nickname": t.nickname or "",
        "url": t.url or "",
        "ip": t.ip or "",
        "network": t.network or "",
        "port": t.port or "",
        "route": t.route or "/",
        "service": t.service or "http",
        "tls_verify": bool(t.tls_verify if t.tls_verify is not None else True),
        "endpoint": t.endpoint or "",
        "feed_path": t.feed_path or "",
        "adapter": t.adapter or "",
        "crawl_depth": t.crawl_depth if t.crawl_depth is not None else 2,
        "schedule_frequency": sched.get("frequency", ""),
        "schedule_time": sched.get("time", ""),
        "schedule_day": sched.get("day", ""),
        "schedule_timezone": sched.get("timezone", "UTC"),
    }


def _form_to_target(form, existing=None):
    """Read request.form and return a CrawlerTarget (new or updated)."""
    import yaml as _yaml
    from flask_app.models.crawler_target import CrawlerTarget

    t = existing or CrawlerTarget()
    t.target_type = form.get("target_type", "service")
    t.nickname = form.get("nickname", "").strip() or None
    t.url = form.get("url", "").strip() or None
    t.ip = form.get("ip", "").strip() or None
    t.network = form.get("network", "").strip() or None
    port_raw = form.get("port", "").strip()
    t.port = int(port_raw) if port_raw.isdigit() else None
    t.route = form.get("route", "/").strip() or "/"
    t.service = form.get("service_protocol", "http")
    t.tls_verify = form.get("tls_verify") == "on"
    depth_raw = form.get("crawl_depth", "2").strip()
    t.crawl_depth = int(depth_raw) if depth_raw.isdigit() else 2
    t.endpoint = form.get("endpoint", "").strip() or None
    t.feed_path = form.get("feed_path", "").strip() or None
    t.adapter = form.get("adapter", "").strip() or None

    freq = form.get("schedule_frequency", "").strip()
    if freq:
        sched = {
            "frequency": freq,
            "time": form.get("schedule_time", "02:00").strip(),
            "timezone": form.get("schedule_timezone", "UTC").strip(),
        }
        day = form.get("schedule_day", "").strip()
        if day:
            sched["day"] = int(day) if day.isdigit() else day
        t.schedule_yaml = _yaml.dump(sched)
    else:
        t.schedule_yaml = None

    return t


@admin_bp.route("/targets")
@admin_required
def targets():
    """
    Input: None
    Output: rendered targets list page with inline add/edit form
    """
    from flask_app import db
    from flask_app.models.crawler_target import CrawlerTarget

    health = _check_services()
    all_targets = [_target_to_dict(t)
                   for t in db.session.query(CrawlerTarget).order_by(CrawlerTarget.id).all()]

    return render_template(
        "admin/targets.html",
        targets=all_targets,
        editing=None,
        opensearch_up=health.get("opensearch", {}).get("status") == "up",
        nutch_up=health.get("nutch", {}).get("status") == "up",
        llm_api_up=health.get("llm_api", {}).get("status") == "up",
    )


@admin_bp.route("/targets/add", methods=["POST"])
@admin_required
def add_target():
    """
    Input: target form fields
    Output: redirect to targets list
    Details:
        Creates a new CrawlerTarget from the submitted form.
    """
    from flask_app import db

    t = _form_to_target(request.form)
    db.session.add(t)
    db.session.commit()
    flash(f"Target '{t.nickname or t.network}' added.", "success")
    return redirect(url_for("admin.targets"))


@admin_bp.route("/targets/<int:target_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_target(target_id):
    """
    Input: target_id; form fields on POST
    Output: GET returns targets page with form pre-filled; POST saves and redirects
    """
    from flask_app import db
    from flask_app.models.crawler_target import CrawlerTarget

    t = db.session.get(CrawlerTarget, target_id)
    if t is None:
        abort(404)

    if request.method == "POST":
        _form_to_target(request.form, existing=t)
        db.session.commit()
        flash(f"Target '{t.nickname or t.network}' updated.", "success")
        return redirect(url_for("admin.targets"))

    health = _check_services()
    all_targets = [_target_to_dict(x)
                   for x in db.session.query(CrawlerTarget).order_by(CrawlerTarget.id).all()]
    return render_template(
        "admin/targets.html",
        targets=all_targets,
        editing=_target_to_dict(t),
        opensearch_up=health.get("opensearch", {}).get("status") == "up",
        nutch_up=health.get("nutch", {}).get("status") == "up",
        llm_api_up=health.get("llm_api", {}).get("status") == "up",
    )


@admin_bp.route("/targets/<int:target_id>/delete", methods=["POST"])
@admin_required
def delete_target(target_id):
    """
    Input: target_id
    Output: redirect to targets list after deleting the target
    """
    from flask_app import db
    from flask_app.models.crawler_target import CrawlerTarget
    from flask_app.models.crawl_job import CrawlJob

    t = db.session.get(CrawlerTarget, target_id)
    if t:
        db.session.query(CrawlJob).filter_by(target_id=t.id).update({"target_id": None})
        db.session.delete(t)
        db.session.commit()
        flash(f"Target deleted.", "success")
    return redirect(url_for("admin.targets"))


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
    try:
        celery_crawl.delay(target_id)
        flash(f"Crawl dispatched for target {target_id}.", "success")
    except Exception:
        logger.warning("Task dispatch failed — Redis unreachable", exc_info=True)
        flash("Task queue unavailable — Redis is not reachable", "error")
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
    try:
        celery_reindex.delay(target_id)
        flash(f"Reindex dispatched for target {target_id}.", "success")
    except Exception:
        logger.warning("Task dispatch failed — Redis unreachable", exc_info=True)
        flash("Task queue unavailable — Redis is not reachable", "error")
    return redirect(url_for("admin.jobs"))


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
            if job.target_id is None:
                target_cache[None] = "—"
            else:
                t = db.session.get(CrawlerTarget, job.target_id)
                target_cache[job.target_id] = t.nickname if t else "(deleted)"
        duration = None
        if job.started_at and job.finished_at:
            duration = str(job.finished_at - job.started_at).split(".")[0]
        rows.append({
            "id": job.id,
            "kind": job.kind or "crawl",
            "target": target_cache[job.target_id],
            "status": job.status or "unknown",
            "progress": 100 if job.status in ("success", "failure") else 0,
            "started_at": str(job.started_at)[:16] if job.started_at else "—",
            "finished_at": str(job.finished_at)[:16] if job.finished_at else "—",
            "took": duration,
            "message": job.message,
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


@admin_bp.route("/jobs/<int:job_id>/logs")
@admin_required
def job_logs(job_id):
    """
    Input: job_id URL param
    Output: JSON with job status and error message
    Details:
        Returns the stored error message and (if available) the Celery
        task traceback from the result backend.
    """
    from flask_app import db
    from flask_app.models.crawl_job import CrawlJob
    from flask import jsonify

    job = db.session.get(CrawlJob, job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404

    result = {
        "id": job.id,
        "status": job.status,
        "message": job.message,
        "traceback": None,
    }

    # Try to get the full traceback from Celery result backend
    if job.task_id:
        try:
            from celery_worker.app import celery
            ar = celery.AsyncResult(job.task_id)
            if ar.failed():
                result["traceback"] = str(ar.traceback)
        except Exception:
            logger.warning("Failed to fetch Celery traceback for job %s", job_id, exc_info=True)

    return jsonify(result)


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
    Input: form fields (LLM settings, global defaults) or yaml (bulk import)
    Output: rendered config page; on POST saves settings or imports YAML
    """
    from flask_app import db
    from flask_app.config import Config

    yaml_text = ""
    validation = None

    if request.method == "POST":
        action = request.form.get("action", "settings")

        if action == "yaml_import":
            # Bulk YAML import path
            from flask_app.config_parser import parse_config, persist_targets
            uploaded = request.files.get("upload")
            if uploaded and uploaded.filename:
                yaml_text = uploaded.read().decode("utf-8", errors="replace")
            else:
                yaml_text = request.form.get("yaml", "").strip()
            try:
                parsed = parse_config(yaml_text)
                persist_targets(yaml_text, parsed, db.session)
                validation = {"ok": True, "errors": [], "warnings": [f"{len(parsed)} target(s) imported."]}
                flash(f"YAML imported — {len(parsed)} target(s) loaded.", "success")
            except Exception as exc:
                logger.warning("YAML parse/import failed", exc_info=True)
                validation = {"ok": False, "errors": [{"line": None, "message": str(exc)}], "warnings": []}
                flash("YAML parse failed.", "error")
        else:
            # Settings form path — persist to system_settings table
            ai_summary_enabled = "1" if request.form.get("ai_summary_enabled") else "0"
            llm_embed_model = request.form.get("llm_embed_model", "").strip()
            llm_gen_model = request.form.get("llm_gen_model", "").strip()

            model_error = _validate_llm_model(llm_gen_model) if llm_gen_model else None
            if model_error:
                flash(model_error, "error")
            else:
                _upsert_setting(db.session, "llm.ai_summary_enabled", ai_summary_enabled)
                if llm_embed_model:
                    _upsert_setting(db.session, "llm.embed_model", llm_embed_model)
                if llm_gen_model:
                    _upsert_setting(db.session, "llm.gen_model", llm_gen_model)
                db.session.commit()
                flash("Settings saved.", "success")

    # Build current YAML snapshot from targets for export
    from flask_app.models.crawler_target import CrawlerTarget
    import yaml as _yaml
    targets = db.session.query(CrawlerTarget).order_by(CrawlerTarget.id).all()
    if targets and targets[0].yaml_source:
        yaml_text = targets[0].yaml_source
    elif targets:
        # Generate YAML from current targets
        target_dicts = []
        for t in targets:
            d = {"type": t.target_type}
            if t.nickname: d["nickname"] = t.nickname
            if t.url: d["url"] = t.url
            if t.network: d["network"] = t.network
            if t.port: d["port"] = t.port
            if t.route and t.route != "/": d["route"] = t.route
            if t.service: d["service"] = t.service
            if t.tls_verify is False: d["tls_verify"] = False
            if t.endpoint: d["endpoint"] = t.endpoint
            if t.feed_path: d["feed_path"] = t.feed_path
            if t.adapter: d["adapter"] = t.adapter
            if t.schedule_yaml:
                try:
                    d["schedule"] = _yaml.safe_load(t.schedule_yaml)
                except Exception:
                    logger.warning("YAML export: malformed schedule_yaml for target %s", t.id, exc_info=True)
            target_dicts.append(d)
        yaml_text = _yaml.dump({"defaults": {}, "targets": target_dicts},
                               default_flow_style=False, allow_unicode=True)

    from flask_app.models.system_setting import SystemSetting

    def _setting(key, default):
        row = db.session.get(SystemSetting, key)
        return row.value if row else default

    ai_summary_enabled = _setting("llm.ai_summary_enabled", "1") != "0"

    return render_template(
        "admin/config.html",
        yaml_text=yaml_text,
        validation=validation,
        last_saved="—",
        llm_api_base=Config.LLM_API_BASE,
        llm_embed_model=_setting("llm.embed_model", Config.LLM_EMBED_MODEL),
        llm_gen_model=_setting("llm.gen_model", Config.LLM_GEN_MODEL),
        ai_summary_enabled=ai_summary_enabled,
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
        logger.warning("YAML validation failed", exc_info=True)
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


# ── Users ──────────────────────────────────────────────────────────────────

@admin_bp.route("/users")
@admin_required
def users():
    """
    Input: None
    Output: rendered user list page with promote/demote buttons
    Details:
        Lists all User rows ordered by username. Admins can promote any user
        to admin role or demote any admin to user role (self-demote blocked).
    """
    from flask_app import db
    from flask_app.models.user import User

    all_users = db.session.query(User).order_by(User.username).all()
    return render_template("admin/users.html", users=all_users)


@admin_bp.route("/users/<int:user_id>/promote", methods=["POST"])
@admin_required
def promote_user(user_id):
    """
    Input: user_id URL param
    Output: redirect to users list
    Details:
        Sets role='admin' for the target user. No-op if already admin.
    """
    from flask_app import db
    from flask_app.models.user import User

    u = db.session.get(User, user_id)
    if u is None:
        abort(404)
    u.role = "admin"
    db.session.commit()
    flash(f"'{u.username}' promoted to admin.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/demote", methods=["POST"])
@admin_required
def demote_user(user_id):
    """
    Input: user_id URL param
    Output: redirect to users list
    Details:
        Sets role='user' for the target user. Blocks self-demote.
    """
    from flask_app import db
    from flask_app.models.user import User

    u = db.session.get(User, user_id)
    if u is None:
        abort(404)
    if u.id == current_user.id:
        flash("You cannot demote yourself.", "error")
        return redirect(url_for("admin.users"))
    u.role = "user"
    db.session.commit()
    flash(f"'{u.username}' demoted to user.", "success")
    return redirect(url_for("admin.users"))


if __name__ == "__main__":
    pass
