"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    API blueprint.  URL prefix /api.  CSRF-exempt (registered in __init__.py).

    Two audiences share one blueprint:

    Browser / HTMX endpoints  (/api/*)
        Session-authenticated.  Return JSON or HTML fragments consumed by the
        web UI.  These endpoints existed before the token API was added and are
        not part of the versioned surface.

    Versioned REST API  (/api/v1/*)
        Accepts Bearer token auth OR an active session.  All responses are JSON.
        CSRF-exempt — callers authenticate via token, not form session.
        Used by the shse CLI, the MCP server, and any programmatic client.
        Auth helpers: _require_auth() / _require_admin().
"""
# Imports
import hashlib
import logging
import time

from flask import Blueprint, abort, jsonify, render_template, request, session
from flask_login import current_user, login_user

from flask_app import db
from flask_app.services.opensearch import get_client
from flask_app.services.search import preprocess_query, execute_bm25, semantic_results

# Globals
api_bp = Blueprint("api", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)

_INDEX_NAME          = "shse_pages"
_PAGE_SIZE           = 10
_SEMANTIC_CACHE_TTL  = 3600  # 1 hour


# ── Redis cache helpers (browser semantic endpoints) ──────────────────────────

def _redis():
    """Return a Redis client using the app's configured host/port/password."""
    import redis
    from flask_app.config import Config
    return redis.Redis(
        host=Config.REDIS_HOST,
        port=Config.REDIS_PORT,
        password=Config.REDIS_PASSWORD or None,
        db=1,
    )


def _cache_key(component, q):
    digest = hashlib.sha256(q.encode()).hexdigest()[:16]
    return f"shse:semantic:{component}:{digest}"


def _cache_get(component, q):
    try:
        val = _redis().get(_cache_key(component, q))
        return val.decode() if val else None
    except Exception:
        logger.warning("Redis cache read failed", exc_info=True)
        return None


def _cache_set(component, q, html):
    try:
        _redis().setex(_cache_key(component, q), _SEMANTIC_CACHE_TTL, html)
    except Exception:
        logger.warning("Redis cache write failed", exc_info=True)


# ── Auth helpers (versioned API) ──────────────────────────────────────────────

def _require_auth():
    """
    Input:  None (reads Flask request context)
    Output: None on success; (Response, int) tuple on failure
    Details:
        1. Checks SystemSetting "api.enabled" — aborts 503 if "0".
        2. Passes through if current_user already authenticated (session).
        3. Otherwise validates "Bearer shse_..." header via ApiToken.verify()
           and calls login_user() with fresh=False.
        4. Returns JSON 401 if neither check passes.
        Callers must return the tuple immediately if not None.
    """
    from flask_app.models.api_token import ApiToken
    from flask_app.models.system_setting import SystemSetting

    try:
        enabled_row = db.session.get(SystemSetting, "api.enabled")
        if enabled_row and enabled_row.value == "0":
            abort(503, description="API disabled")
    except Exception as _exc:
        from werkzeug.exceptions import HTTPException
        if isinstance(_exc, HTTPException):
            raise
        logger.exception("_require_auth: could not read api.enabled setting")
        return jsonify({"error": "internal error checking API status"}), 500

    if current_user.is_authenticated:
        return None

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer shse_"):
        raw_token = auth[7:]
        try:
            token = ApiToken.verify(raw_token)
        except Exception:
            logger.exception("_require_auth: token verification error")
            return jsonify({"error": "token verification failed"}), 500
        if token is not None:
            login_user(token.user, fresh=False)
            return None

    return jsonify({"error": "authentication required"}), 401


def _require_admin():
    """
    Input:  None (reads Flask request context)
    Output: None on success; (Response, int) tuple on failure
    Details:
        Calls _require_auth() then verifies current_user.role == "admin".
        Returns 403 JSON if role check fails.
    """
    result = _require_auth()
    if result is not None:
        return result
    if not current_user.is_authenticated or current_user.role != "admin":
        return jsonify({"error": "admin role required"}), 403
    return None


def _token_to_dict(t) -> dict:
    """
    Input:  ApiToken ORM row
    Output: JSON-serialisable dict; never includes token_hash or raw token
    """
    return {
        "id":           t.id,
        "name":         t.name,
        "user_id":      t.user_id,
        "created_at":   t.created_at.isoformat() if t.created_at else None,
        "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        "expires_at":   t.expires_at.isoformat() if t.expires_at else None,
        "revoked_at":   t.revoked_at.isoformat() if t.revoked_at else None,
        "active":       t.is_active,
    }


def _log_v1(method, path):
    logger.info("api/v1 %s %s user_id=%s", method, path,
                getattr(current_user, "id", "anon"))


# ── Browser / HTMX endpoints  (/api/*) ───────────────────────────────────────

@api_bp.route("/search")
def search():
    """
    Input: q (query string), page (1-indexed, default 1), tab (default 'all')
    Output: JSON object with results, total, timing, source facets,
            vector_hits, and optional ai_summary
    Details:
        Full BM25 + semantic search endpoint consumed by the HTMX search page.
        Returns 200 with empty results on any failure.
    """
    q = request.args.get("q", "").strip()
    tab = request.args.get("tab", "all")
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    preprocessed_q, search_q, rewritten_q = preprocess_query(q) if q else (q, q, None)

    result_rows = []
    total = 0
    took_ms = 0
    search_error = None
    sources = []
    page_count = 1
    vector_hits = []
    ai_summary = None
    show_bm25_warning = False

    if q:
        try:
            took_ms, total, page_count, hits, sources = execute_bm25(
                search_q, page=page, page_size=_PAGE_SIZE,
            )
            for h in hits:
                src = h.get("_source", {})
                hl = h.get("highlight", {})
                frags = hl.get("title", []) + hl.get("text", [src.get("text", "")[:300]])
                snippet = " … ".join(frags[:3])
                result_rows.append({
                    "id": h["_id"],
                    "title": src.get("title") or src.get("url", ""),
                    "url": src.get("url", ""),
                    "service": src.get("service_nickname", ""),
                    "port": src.get("port", 80),
                    "crawled_at": (src.get("crawled_at") or "")[:19],
                    "content_type": src.get("content_type", ""),
                    "snippet": snippet,
                    "vectorized": bool(src.get("vectorized", False)),
                })

        except Exception as _exc:
            logger.exception("BM25 search failed on API endpoint: %s", _exc)
            if getattr(current_user, "role", "") == "admin":
                search_error = str(_exc)
            else:
                search_error = "A search error occurred."

        vector_hits, ai_summary, show_bm25_warning, _chips = semantic_results(search_q)

    return jsonify({
        "q":               q,
        "preprocessed_q":  preprocessed_q if preprocessed_q != q else None,
        "rewritten_q":     rewritten_q,
        "tab":             tab,
        "page":            page,
        "page_count":      page_count,
        "total":           total,
        "took_ms":         took_ms,
        "show_bm25_warning": show_bm25_warning,
        "results":         result_rows,
        "sources":         sources,
        "vector_hits":     vector_hits,
        "ai_summary":      ai_summary,
        "search_error":    search_error,
    })


@api_bp.route("/stats")
def stats():
    """
    Input:  None
    Output: JSON {docs, services, last_crawl}; zeros when OpenSearch is unreachable
    """
    try:
        client = get_client()
        count = client.count(index=_INDEX_NAME).get("count", 0)
        agg = client.search(index=_INDEX_NAME, body={
            "size": 0,
            "aggs": {"svc": {"cardinality": {"field": "service_nickname"}}},
        })
        svc_count = agg["aggregations"]["svc"]["value"]
        last = client.search(index=_INDEX_NAME, body={
            "size": 1, "sort": [{"crawled_at": "desc"}], "_source": ["crawled_at"],
        })
        hits = last["hits"]["hits"]
        last_crawl = hits[0]["_source"].get("crawled_at", "")[:19] if hits else None
        return jsonify({"docs": count, "services": svc_count, "last_crawl": last_crawl})
    except Exception:
        logger.warning("OpenSearch unavailable — returning zero stats", exc_info=True)
        return jsonify({"docs": 0, "services": 0, "last_crawl": None})


@api_bp.route("/semantic/vector")
def semantic_vector():
    """
    Input:  q (query string)
    Output: HTML fragment for the semantic matches section
    Details: Runs k-NN vector search; result cached in Redis for 1 hour.
    """
    q = request.args.get("q", "").strip()
    if not q:
        return ""
    cached = _cache_get("vector", q)
    if cached:
        return cached
    from flask_app.services.search import get_vector_hits
    vector_hits, embedding_up = get_vector_hits(q)
    html = render_template("_semantic_vector.html", vector_hits=vector_hits,
                           show_bm25_warning=not embedding_up)
    _cache_set("vector", q, html)
    return html


@api_bp.route("/semantic/summary")
def semantic_summary():
    """
    Input:  q (query string)
    Output: HTML fragment for the AI summary section
    Details:
        Builds RAG summary from vector hits. Respects global admin gate and
        per-user session preference. Result cached in Redis for 1 hour.
    """
    from flask_app.services.llm import is_llm_available
    if not is_llm_available():
        return ""
    try:
        from flask_app.models.system_setting import SystemSetting
        row = db.session.get(SystemSetting, "llm.ai_summary_enabled")
        if row is not None and row.value == "0":
            return ""
    except Exception:
        logger.warning("semantic_summary: could not read admin setting", exc_info=True)
    if not session.get("ai_summary_enabled", True):
        return ""
    q = request.args.get("q", "").strip()
    if not q:
        return ""
    cached = _cache_get("summary", q)
    if cached:
        return cached
    from flask_app.services.search import get_vector_hits, _build_ai_summary
    preprocessed_q, _, _ = preprocess_query(q)
    vector_hits, _ = get_vector_hits(q)
    ai_summary = _build_ai_summary(vector_hits, q, preprocessed_q=preprocessed_q)
    html = render_template("_semantic_summary.html", ai_summary=ai_summary)
    _cache_set("summary", q, html)
    return html


@api_bp.route("/semantic/chips")
def semantic_chips():
    """
    Input:  q (query string)
    Output: HTML fragment for the suggested searches section
    Details: Generates keyword chips via the rewriter model; cached 1 hour.
    """
    q = request.args.get("q", "").strip()
    if not q:
        return ""
    cached = _cache_get("chips", q)
    if cached:
        return cached
    from flask_app.services.llm import generate_keywords
    keyword_chips = generate_keywords(q, [])
    html = render_template("_semantic_chips.html", q=q, keyword_chips=keyword_chips)
    _cache_set("chips", q, html)
    return html


@api_bp.route("/jobs/<int:job_id>/logs")
def job_logs(job_id):
    """
    Input:  job_id — URL path integer
    Output: JSON {id, status, message, traceback}
    Details:
        No auth required — used by the JS log modal which runs in an authenticated
        browser session but calls this as a plain fetch without extra headers.
        Only returns data for the requested job; no enumeration risk.
    """
    from flask_app.models.crawl_job import CrawlJob

    job = db.session.get(CrawlJob, job_id)
    if job is None:
        return jsonify({"error": "not found"}), 404

    result = {"id": job.id, "status": job.status, "message": job.message, "traceback": None}
    if job.task_id:
        try:
            from celery_worker.app import celery
            ar = celery.AsyncResult(job.task_id)
            if ar.failed():
                result["traceback"] = str(ar.traceback)
        except Exception:
            logger.warning("Failed to fetch Celery traceback for job %s", job_id, exc_info=True)
    return jsonify(result)


@api_bp.route("/admin-check")
def admin_check():
    """
    Input:  None (reads Flask-Login session)
    Output: 200 for authenticated admin; 403 otherwise
    Details:
        Used by Nginx auth_request to gate /admin/* routes at the proxy layer.
        Only the status code is meaningful to Nginx.
    """
    if current_user.is_authenticated and current_user.role == "admin":
        return "", 200
    return "", 403


# ── Versioned REST API  (/api/v1/*) ──────────────────────────────────────────

@api_bp.route("/v1/me", methods=["GET"])
def v1_me():
    """
    Input:  None
    Output: JSON {"ok": true, "id", "username", "role"}
    Details:
        Identity check used by the CLI config test command to verify that
        credentials are valid and surface the authenticated user's role.
    """
    err = _require_auth()
    if err is not None:
        return err
    return jsonify({
        "ok":       True,
        "id":       current_user.id,
        "username": current_user.username,
        "role":     current_user.role,
    }), 200


@api_bp.route("/v1/targets", methods=["GET"])
def v1_list_targets():
    """
    Input:  None
    Output: JSON array of all CrawlerTarget rows (admin only)
    """
    err = _require_admin()
    if err is not None:
        return err
    _log_v1(request.method, request.path)

    from flask_app.models.crawler_target import CrawlerTarget

    targets = db.session.execute(
        db.select(CrawlerTarget).order_by(CrawlerTarget.id)
    ).scalars().all()
    return jsonify([
        {
            "id":          t.id,
            "nickname":    t.nickname,
            "target_type": t.target_type,
            "url":         t.url,
            "ip":          t.ip,
            "network":     t.network,
            "port":        t.port,
            "route":       t.route,
            "service":     t.service,
            "tls_verify":  t.tls_verify,
            "crawl_depth": t.crawl_depth,
            "endpoint":    t.endpoint,
            "feed_path":   t.feed_path,
            "adapter":     t.adapter,
        }
        for t in targets
    ]), 200


@api_bp.route("/v1/targets", methods=["POST"])
def v1_create_target():
    """
    Input:  JSON body with target fields
    Output: JSON {"ok": true, "id": <new_id>} with 201 on success
    Details: Admin role required.
    """
    err = _require_admin()
    if err is not None:
        return err
    _log_v1(request.method, request.path)

    from flask_app.models.crawler_target import CrawlerTarget

    data = request.json or {}
    t = CrawlerTarget()
    t.target_type = data.get("target_type", "service")
    t.nickname    = (data.get("nickname") or "").strip() or None
    t.url         = (data.get("url") or "").strip() or None
    t.ip          = (data.get("ip") or "").strip() or None
    t.network     = (data.get("network") or "").strip() or None
    port_raw      = str(data.get("port", "")).strip()
    t.port        = int(port_raw) if port_raw.isdigit() else None
    t.route       = (data.get("route") or "/").strip() or "/"
    t.service     = data.get("service_protocol", "http") or "http"
    t.tls_verify  = bool(data.get("tls_verify", True))
    depth_raw     = str(data.get("crawl_depth", "2")).strip()
    t.crawl_depth = int(depth_raw) if depth_raw.isdigit() else 2
    t.endpoint    = (data.get("endpoint") or "").strip() or None
    t.feed_path   = (data.get("feed_path") or "").strip() or None
    t.adapter     = (data.get("adapter") or "").strip() or None

    try:
        db.session.add(t)
        db.session.commit()
    except Exception:
        logger.exception("v1_create_target: db commit failed")
        db.session.rollback()
        return jsonify({"error": "database error saving target"}), 500

    logger.info("v1_create_target: id=%s nickname=%s user_id=%s",
                t.id, t.nickname, current_user.id)
    return jsonify({"ok": True, "id": t.id}), 201


@api_bp.route("/v1/targets/<int:target_id>", methods=["DELETE"])
def v1_delete_target(target_id):
    """
    Input:  target_id — URL path integer
    Output: JSON {"ok": true} on success; 404 if not found (admin only)
    """
    err = _require_admin()
    if err is not None:
        return err
    _log_v1(request.method, request.path)

    from flask_app.models.crawler_target import CrawlerTarget

    t = db.session.get(CrawlerTarget, target_id)
    if t is None:
        return jsonify({"error": "target not found"}), 404
    try:
        db.session.delete(t)
        db.session.commit()
    except Exception:
        logger.exception("v1_delete_target: db commit failed target_id=%s", target_id)
        db.session.rollback()
        return jsonify({"error": "database error deleting target"}), 500
    return jsonify({"ok": True}), 200


@api_bp.route("/v1/targets/<int:target_id>/crawl", methods=["POST"])
def v1_trigger_crawl(target_id):
    """
    Input:  target_id — URL path integer
    Output: JSON {"ok": true, "task_id": str} with 202 on success (admin only)
    """
    err = _require_admin()
    if err is not None:
        return err
    _log_v1(request.method, request.path)

    from flask_app.models.crawler_target import CrawlerTarget

    t = db.session.get(CrawlerTarget, target_id)
    if t is None:
        return jsonify({"error": "target not found"}), 404
    try:
        from celery_worker.tasks.crawl import crawl_target as celery_crawl
        result  = celery_crawl.delay(target_id)
        task_id = result.id if result is not None else None
    except Exception:
        logger.warning("v1_trigger_crawl: task dispatch failed target_id=%s",
                       target_id, exc_info=True)
        return jsonify({"error": "task queue unavailable"}), 503

    logger.info("v1_trigger_crawl: target_id=%s task_id=%s user_id=%s",
                target_id, task_id, current_user.id)
    return jsonify({"ok": True, "task_id": task_id}), 202


@api_bp.route("/v1/jobs", methods=["GET"])
def v1_list_jobs():
    """
    Input:  Optional ?status= query parameter
    Output: JSON array of up to 50 recent CrawlJob rows (admin only)
    """
    err = _require_admin()
    if err is not None:
        return err
    _log_v1(request.method, request.path)

    from flask_app.models.crawl_job import CrawlJob

    status_filter = request.args.get("status")
    query = db.select(CrawlJob).order_by(CrawlJob.id.desc()).limit(50)
    if status_filter:
        query = (
            db.select(CrawlJob)
            .filter_by(status=status_filter)
            .order_by(CrawlJob.id.desc())
            .limit(50)
        )
    jobs = db.session.execute(query).scalars().all()
    return jsonify([
        {
            "id":          j.id,
            "task_id":     j.task_id,
            "target_id":   j.target_id,
            "kind":        j.kind,
            "status":      j.status,
            "progress":    j.progress,
            "started_at":  j.started_at.isoformat() if j.started_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            "message":     j.message,
        }
        for j in jobs
    ]), 200


@api_bp.route("/v1/jobs/<int:job_id>", methods=["GET"])
def v1_get_job(job_id):
    """
    Input:  job_id — URL path integer
    Output: JSON dict of the CrawlJob row; 404 if not found (admin only)
    """
    err = _require_admin()
    if err is not None:
        return err
    _log_v1(request.method, request.path)

    from flask_app.models.crawl_job import CrawlJob

    j = db.session.get(CrawlJob, job_id)
    if j is None:
        return jsonify({"error": "job not found"}), 404
    return jsonify({
        "ok":          True,
        "id":          j.id,
        "task_id":     j.task_id,
        "target_id":   j.target_id,
        "kind":        j.kind,
        "status":      j.status,
        "progress":    j.progress,
        "started_at":  j.started_at.isoformat() if j.started_at else None,
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        "message":     j.message,
    }), 200


@api_bp.route("/v1/search", methods=["GET"])
def v1_search():
    """
    Input:  ?q=, ?page= (default 1), ?limit= (default 10, max 50)
    Output: JSON {"ok": true, "hits": [...], "total": int, "took_ms": int}
    Details:
        Public endpoint — no authentication required, consistent with the web
        UI search page.  Returns empty results gracefully when the index does
        not exist yet.
    """
    _log_v1(request.method, request.path)
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"ok": True, "hits": [], "total": 0, "took_ms": 0}), 200

    try:
        from flask_app.services.search import bm25_body
        client = get_client()
        page   = max(1, int(request.args.get("page",  1)))
        limit  = min(50, max(1, int(request.args.get("limit", 10))))
        body   = bm25_body(q, page=page, page_size=limit)
        t0     = time.monotonic()
        resp   = client.search(index=_INDEX_NAME, body=body)
        took   = int((time.monotonic() - t0) * 1000)
        total  = resp["hits"]["total"]["value"]
        hits   = [
            {
                "id":      h["_id"],
                "score":   round(h.get("_score", 0.0), 3),
                "url":     h["_source"].get("url", ""),
                "title":   h["_source"].get("title") or h["_source"].get("url", ""),
                "service": h["_source"].get("service_nickname", ""),
                "snippet": h["_source"].get("text", "")[:300],
            }
            for h in resp["hits"]["hits"]
        ]
    except Exception as _exc:
        _exc_str = str(_exc).lower()
        if "index_not_found" in _exc_str or "no such index" in _exc_str:
            logger.warning("v1_search: index does not exist yet q=%r", q)
            return jsonify({"ok": True, "hits": [], "total": 0, "took_ms": 0}), 200
        logger.exception("v1_search: query failed q=%r", q)
        return jsonify({"error": "search service unavailable"}), 503

    return jsonify({"ok": True, "hits": hits, "total": total, "took_ms": took}), 200


@api_bp.route("/v1/tokens", methods=["GET"])
def v1_list_tokens():
    """
    Input:  None
    Output: JSON array of token dicts (own tokens; admin sees all)
    Details: Token hashes are never included in the response.
    """
    err = _require_auth()
    if err is not None:
        return err
    _log_v1(request.method, request.path)

    from flask_app.models.api_token import ApiToken

    if getattr(current_user, "role", "") == "admin":
        tokens = db.session.execute(
            db.select(ApiToken).order_by(ApiToken.id.desc())
        ).scalars().all()
    else:
        tokens = db.session.execute(
            db.select(ApiToken).filter_by(user_id=current_user.id)
            .order_by(ApiToken.id.desc())
        ).scalars().all()
    return jsonify([_token_to_dict(t) for t in tokens]), 200


@api_bp.route("/v1/tokens", methods=["POST"])
def v1_generate_token():
    """
    Input:  JSON body {"name": "<label>"}
    Output: JSON {"ok": true, "token": "<raw>", ...} — raw token returned ONCE
    Details:
        The raw token is included only in this response and cannot be recovered
        afterwards.  Callers must store it immediately.
    """
    err = _require_auth()
    if err is not None:
        return err
    _log_v1(request.method, request.path)

    from flask_app.models.api_token import ApiToken

    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    try:
        token, raw = ApiToken.generate(name, current_user)
        db.session.add(token)
        db.session.commit()
    except Exception:
        logger.exception("v1_generate_token: db commit failed user_id=%s",
                         current_user.id)
        db.session.rollback()
        return jsonify({"error": "database error saving token"}), 500

    result = _token_to_dict(token)
    result["token"]   = raw
    result["warning"] = "Store this token now — it cannot be retrieved again."
    return jsonify({"ok": True, **result}), 201


@api_bp.route("/v1/tokens/<int:token_id>", methods=["DELETE"])
def v1_revoke_token(token_id):
    """
    Input:  token_id — URL path integer
    Output: JSON {"ok": true}; 404 if not found; 403 if not authorised
    Details:
        Token owners can revoke their own tokens. Admins can revoke any token.
        Sets revoked_at to now; is_active becomes False immediately.
    """
    err = _require_auth()
    if err is not None:
        return err
    _log_v1(request.method, request.path)

    from flask_app.models.api_token import ApiToken
    from datetime import datetime

    token = db.session.get(ApiToken, token_id)
    if token is None:
        return jsonify({"error": "token not found"}), 404
    if token.user_id != current_user.id and getattr(current_user, "role", "") != "admin":
        return jsonify({"error": "cannot revoke another user's token"}), 403

    try:
        token.revoked_at = datetime.utcnow()
        db.session.commit()
    except Exception:
        logger.exception("v1_revoke_token: db commit failed token_id=%s", token_id)
        db.session.rollback()
        return jsonify({"error": "database error revoking token"}), 500

    logger.info("v1_revoke_token: token_id=%s revoked by user_id=%s",
                token_id, current_user.id)
    return jsonify({"ok": True}), 200


if __name__ == "__main__":
    pass
