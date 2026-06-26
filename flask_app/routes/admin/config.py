"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Admin config concern: crawler-config editing, LLM/global settings, and bulk
    YAML import/validation. Registers its routes on the shared ``admin_bp``.
"""
# Imports
import logging

import requests as _requests
from flask import render_template, request, flash

from flask_app.routes.admin import admin_bp
from flask_app.routes.admin._shared import admin_required, _PROBE_TIMEOUT

# Globals
logger = logging.getLogger(__name__)


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
            llm_rewrite_model = request.form.get("llm_rewrite_model", "").strip()

            model_error = _validate_llm_model(llm_gen_model) if llm_gen_model else None
            if model_error:
                flash(model_error, "error")
            else:
                _upsert_setting(db.session, "llm.ai_summary_enabled", ai_summary_enabled)
                if llm_embed_model:
                    _upsert_setting(db.session, "llm.embed_model", llm_embed_model)
                if llm_gen_model:
                    _upsert_setting(db.session, "llm.gen_model", llm_gen_model)
                if llm_rewrite_model:
                    _upsert_setting(db.session, "llm.rewrite_model", llm_rewrite_model)
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
        llm_rewrite_model=_setting("llm.rewrite_model", Config.LLM_REWRITE_MODEL),
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
