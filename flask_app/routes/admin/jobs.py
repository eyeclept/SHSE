"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Admin jobs concern: crawl-job listing, HTMX poll fragments, and per-job
    logs. Registers its routes on the shared ``admin_bp``.
"""
# Imports
import logging

from flask import render_template, request

from flask_app.routes.admin import admin_bp
from flask_app.routes.admin._shared import admin_required

# Globals
logger = logging.getLogger(__name__)

# Translate DB status values to the UI names expected by the jobs template.
# DB:  queued | started | success | failure
# UI:  queued | running | done    | failed
_STATUS_DB_TO_UI = {
    "queued":  "queued",
    "started": "running",
    "success": "done",
    "failure": "failed",
}
_STATUS_UI_TO_DB = {v: k for k, v in _STATUS_DB_TO_UI.items()}


# Functions
def _job_counts():
    """
    Input: None
    Output: dict of UI status -> count (queued, running, done, failed, all)
    Details:
        One GROUP BY status aggregate instead of four separate COUNT queries.
        'all' matches the prior behaviour: the sum of the four known buckets.
    """
    from flask_app import db
    from flask_app.models.crawl_job import CrawlJob
    from sqlalchemy import func

    by_status = dict(
        db.session.query(CrawlJob.status, func.count()).group_by(CrawlJob.status).all()
    )
    counts = {
        "queued":  by_status.get("queued", 0),
        "running": by_status.get("started", 0),
        "done":    by_status.get("success", 0),
        "failed":  by_status.get("failure", 0),
    }
    counts["all"] = sum(counts.values())
    return counts


def _job_rows(status_filter="all"):
    """
    Input: status_filter str ('all' or a specific status)
    Output: list of job dicts for the jobs template
    """
    from flask_app import db
    from flask_app.models.crawl_job import CrawlJob
    from flask_app.models.crawler_target import CrawlerTarget

    q = db.session.query(CrawlJob).order_by(CrawlJob.started_at.desc())
    if status_filter != "all":
        db_status = _STATUS_UI_TO_DB.get(status_filter, status_filter)
        q = q.filter(CrawlJob.status == db_status)
    q = q.limit(100)

    job_list = q.all()

    # Resolve all target nicknames in one IN-clause query instead of a per-row
    # db.session.get(). None target_id -> "—"; an id with no matching row was
    # deleted -> "(deleted)".
    target_cache = {None: "—"}
    target_ids = {j.target_id for j in job_list if j.target_id is not None}
    if target_ids:
        for t in db.session.query(CrawlerTarget).filter(CrawlerTarget.id.in_(target_ids)):
            target_cache[t.id] = t.nickname

    rows = []
    for job in job_list:
        target_name = target_cache.get(job.target_id, "(deleted)")
        duration = None
        if job.started_at and job.finished_at:
            duration = str(job.finished_at - job.started_at).split(".")[0]
        rows.append({
            "id": job.id,
            "kind": job.kind or "crawl",
            "target": target_name,
            "status": _STATUS_DB_TO_UI.get(job.status, job.status) or "unknown",
            "progress": job.progress if job.progress is not None else (100 if job.status in ("success", "failure") else 0),
            "started_at": str(job.started_at)[:16] if job.started_at else "—",
            "finished_at": str(job.finished_at)[:16] if job.finished_at else "—",
            "took": duration,
            "message": job.message,
        })
    return rows


# ── Jobs ───────────────────────────────────────────────────────────────────

@admin_bp.route("/jobs")
@admin_required
def jobs():
    """
    Input: ?status= filter (optional)
    Output: rendered jobs page
    """
    status_filter = request.args.get("status", "all")
    counts = _job_counts()
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
    status_filter = request.args.get("status", "all")
    counts = _job_counts()
    return render_template(
        "admin/_jobs_rows.html",
        jobs=_job_rows(status_filter),
        filter=status_filter,
        counts=counts,
    )


@admin_bp.route("/jobs/<int:job_id>/_row")
@admin_required
def job_row(job_id):
    """
    Input: job_id URL param, ?status= filter
    Output: rendered _job_row.html fragment (single <tr>); HTMX per-row poll target
    Details:
        Returns a single table row for the given job. Running/queued rows
        include hx-* attributes so the row self-polls until the job finishes.
    """
    from flask_app import db
    from flask_app.models.crawl_job import CrawlJob
    from flask_app.models.crawler_target import CrawlerTarget

    job = db.session.get(CrawlJob, job_id)
    if job is None:
        return "", 404

    t = None
    if job.target_id is not None:
        t = db.session.get(CrawlerTarget, job.target_id)
    target_label = t.nickname if t else ("—" if job.target_id is None else "(deleted)")

    duration = None
    if job.started_at and job.finished_at:
        duration = str(job.finished_at - job.started_at).split(".")[0]

    j = {
        "id": job.id,
        "kind": job.kind or "crawl",
        "target": target_label,
        "status": _STATUS_DB_TO_UI.get(job.status, job.status) or "unknown",
        "progress": job.progress if job.progress is not None else (100 if job.status in ("success", "failure") else 0),
        "started_at": str(job.started_at)[:16] if job.started_at else "—",
        "took": duration,
        "message": job.message,
    }
    status_filter = request.args.get("status", "all")
    return render_template("admin/_job_row.html", j=j, filter=status_filter)
