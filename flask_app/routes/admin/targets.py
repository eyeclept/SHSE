"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Admin targets concern: crawler-target CRUD and per-target crawl/reindex
    dispatch. Registers its routes on the shared ``admin_bp``.
"""
# Imports
import logging

from flask import (
    abort, flash, redirect, render_template, request, url_for,
)
from flask_login import current_user

from flask_app.routes.admin import admin_bp
from flask_app.routes.admin._shared import admin_required, _check_services

# Globals
logger = logging.getLogger(__name__)


# Functions
def _target_to_dict(t):
    """Convert a CrawlerTarget ORM row to a plain dict for templates."""
    import yaml as _yaml
    from flask_app.config import Config
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
        "crawl_depth": t.crawl_depth if t.crawl_depth is not None else Config.NUTCH_DEFAULT_DEPTH,
        "schedule_frequency": sched.get("frequency", ""),
        "schedule_time": sched.get("time", ""),
        "schedule_day": sched.get("day", ""),
        "schedule_timezone": sched.get("timezone", "UTC"),
    }


def _form_to_target(form, existing=None):
    """Read request.form and return a CrawlerTarget (new or updated)."""
    import yaml as _yaml
    from flask_app.config import Config
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
    depth_raw = form.get("crawl_depth", str(Config.NUTCH_DEFAULT_DEPTH)).strip()
    t.crawl_depth = min(
        int(depth_raw) if depth_raw.isdigit() else Config.NUTCH_DEFAULT_DEPTH,
        Config.NUTCH_MAX_DEPTH,
    )
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


# ── Targets ────────────────────────────────────────────────────────────────

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

    from flask_app.config import Config as _Cfg
    return render_template(
        "admin/targets.html",
        targets=all_targets,
        editing=None,
        opensearch_up=health.get("opensearch", {}).get("status") == "up",
        nutch_up=health.get("nutch", {}).get("status") == "up",
        llm_api_up=health.get("llm_api", {}).get("status") == "up",
        max_crawl_depth=_Cfg.NUTCH_MAX_DEPTH,
        default_crawl_depth=_Cfg.NUTCH_DEFAULT_DEPTH,
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
    logger.info("add_target: target_id=%s nickname=%s added by user_id=%s",
                t.id, t.nickname, current_user.id)
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
    from flask_app.config import Config as _Cfg
    return render_template(
        "admin/targets.html",
        targets=all_targets,
        editing=_target_to_dict(t),
        opensearch_up=health.get("opensearch", {}).get("status") == "up",
        nutch_up=health.get("nutch", {}).get("status") == "up",
        llm_api_up=health.get("llm_api", {}).get("status") == "up",
        max_crawl_depth=_Cfg.NUTCH_MAX_DEPTH,
        default_crawl_depth=_Cfg.NUTCH_DEFAULT_DEPTH,
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
        logger.info("delete_target: target_id=%s nickname=%s deleted by user_id=%s",
                    t.id, t.nickname, current_user.id)
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
        logger.info("crawl_target: target_id=%s dispatched by user_id=%s", target_id, current_user.id)
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
