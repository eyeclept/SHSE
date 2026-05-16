"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    JSON search API blueprint. Exposes OpenSearch results as structured JSON
    so clients other than the browser (CLI, scripts, integrations) can query
    the index without parsing HTML.
"""
# Imports
import hashlib
import logging
import math

from flask import Blueprint, jsonify, render_template, request, session
from flask_login import current_user
from flask_app.services.opensearch import get_client
from flask_app.services.search import bm25_body_with_dorks, semantic_results
from flask_app.services.query_preprocessor import (
    strip_preamble, normalize, strip_stopwords, expand_synonyms,
)

# Globals
api_bp = Blueprint("api", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)

_INDEX_NAME = "shse_pages"
_PAGE_SIZE = 10
_SEMANTIC_CACHE_TTL = 3600  # 1 hour


def _redis():
    """Return a Redis client using the app's configured host/port."""
    import redis
    from flask_app.config import Config
    return redis.Redis(host=Config.REDIS_HOST, port=Config.REDIS_PORT, db=1)


def _cache_key(component, q):
    digest = hashlib.sha256(q.encode()).hexdigest()[:16]
    return f"shse:semantic:{component}:{digest}"


def _cache_get(component, q):
    try:
        val = _redis().get(_cache_key(component, q))
        return val.decode() if val else None
    except Exception as e:
        logger.warning("Redis cache read failed: %s", e)
        return None


def _cache_set(component, q, html):
    try:
        _redis().setex(_cache_key(component, q), _SEMANTIC_CACHE_TTL, html)
    except Exception as e:
        logger.warning("Redis cache write failed: %s", e)


# Functions
@api_bp.route("/search")
def search():
    """
    Input: q (query string), page (1-indexed, default 1), tab (default 'all')
    Output: JSON object with results, total, timing, source facets,
            vector_hits, and optional ai_summary
    Details:
        Runs a multi_match BM25 query with typo tolerance across text and title.
        When the LLM API is available, also runs vector search and generates
        an AI summary. Returns 200 with empty results on any failure.

    Response shape:
        {
          "q":                  str,
          "tab":                str,
          "page":               int,
          "page_count":         int,
          "total":              int,
          "took_ms":            int,
          "show_bm25_warning":  bool,
          "results": [
            {
              "id":           str,
              "title":        str,
              "url":          str,
              "service":      str,
              "port":         int,
              "crawled_at":   str,
              "content_type": str,
              "snippet":      str,
              "vectorized":   bool
            }
          ],
          "sources":       [{"name": str, "n": int}],
          "vector_hits":   [{"score": float, "service": str, "url": str, "title": str, "snippet": str}],
          "ai_summary":    {"html": str, "sources": [str]} | null
        }
    """
    q = request.args.get("q", "").strip()
    tab = request.args.get("tab", "all")
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    preprocessed_q = expand_synonyms(strip_stopwords(normalize(strip_preamble(q)))) if q else q

    from flask_app.config import Config
    rewritten_q = None
    search_q = preprocessed_q
    if q and Config.QUERY_REWRITE_ENABLED:
        from flask_app.services.llm import rewrite_query
        candidate = rewrite_query(preprocessed_q)
        if candidate and candidate != preprocessed_q:
            rewritten_q = candidate
            search_q = rewritten_q

    result_rows = []
    total = 0
    took_ms = 0
    sources = []
    page_count = 1
    vector_hits = []
    ai_summary = None
    show_bm25_warning = False

    if q:
        try:
            client = get_client()
            body = bm25_body_with_dorks(search_q, page=page, page_size=_PAGE_SIZE)
            resp = client.search(index=_INDEX_NAME, body=body)
            took_ms = resp.get("took", 0)
            total = resp["hits"]["total"]["value"]
            page_count = max(1, math.ceil(total / _PAGE_SIZE))

            for h in resp["hits"]["hits"]:
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

            buckets = resp.get("aggregations", {}).get("by_service", {}).get("buckets", [])
            sources = [{"name": b["key"], "n": b["doc_count"]} for b in buckets]

        except Exception:
            logger.warning("BM25 search failed on API endpoint", exc_info=True)

        # Semantic search + AI summary (use effective search query for embedding)
        vector_hits, ai_summary, show_bm25_warning, _chips = semantic_results(search_q)

    return jsonify({
        "q": q,
        "preprocessed_q": preprocessed_q if preprocessed_q != q else None,
        "rewritten_q": rewritten_q,
        "tab": tab,
        "page": page,
        "page_count": page_count,
        "total": total,
        "took_ms": took_ms,
        "show_bm25_warning": show_bm25_warning,
        "results": result_rows,
        "sources": sources,
        "vector_hits": vector_hits,
        "ai_summary": ai_summary,
    })


@api_bp.route("/stats")
def stats():
    """
    Input: None
    Output: JSON object with document count, service count, and last crawl time
    Details:
        Returns zeros when OpenSearch is unreachable.
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
    Input: q (query string)
    Output: HTML fragment for the semantic matches section
    Details:
        Runs k-NN vector search. Result cached in Redis for 1 hour.
        Returns empty string when q is blank.
    """
    q = request.args.get("q", "").strip()
    if not q:
        return ""
    cached = _cache_get("vector", q)
    if cached:
        return cached

    from flask_app.services.search import get_vector_hits
    vector_hits, embedding_up = get_vector_hits(q)

    html = render_template("_semantic_vector.html",
                           vector_hits=vector_hits,
                           show_bm25_warning=not embedding_up)
    _cache_set("vector", q, html)
    return html


@api_bp.route("/semantic/summary")
def semantic_summary():
    """
    Input: q (query string)
    Output: HTML fragment for the AI summary section
    Details:
        Builds RAG summary from vector hits. Computes its own vector hits
        (cached result from /semantic/vector will be a Redis hit on any
        concurrent or repeat search). Result cached in Redis for 1 hour.
        Returns empty string when AI summary is disabled globally (admin)
        or by the user in their session preference.
    """
    # Admin gate
    try:
        from flask_app import db
        from flask_app.models.system_setting import SystemSetting
        row = db.session.get(SystemSetting, "llm.ai_summary_enabled")
        if row is not None and row.value == "0":
            return ""
    except Exception:
        logger.warning("semantic_summary: could not read admin setting", exc_info=True)

    # Per-user gate
    if not session.get("ai_summary_enabled", True):
        return ""

    q = request.args.get("q", "").strip()
    if not q:
        return ""
    cached = _cache_get("summary", q)
    if cached:
        return cached

    from flask_app.services.search import get_vector_hits, _build_ai_summary
    from flask_app.services.query_preprocessor import (
        strip_preamble, normalize, strip_stopwords, expand_synonyms,
    )
    preprocessed_q = expand_synonyms(strip_stopwords(normalize(strip_preamble(q))))
    vector_hits, _ = get_vector_hits(q)
    ai_summary = _build_ai_summary(vector_hits, q, preprocessed_q=preprocessed_q)

    html = render_template("_semantic_summary.html", ai_summary=ai_summary)
    _cache_set("summary", q, html)
    return html


@api_bp.route("/semantic/chips")
def semantic_chips():
    """
    Input: q (query string)
    Output: HTML fragment for the suggested searches section
    Details:
        Generates keyword chips via the rewriter model. Independent of vector
        hits. Result cached in Redis for 1 hour.
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
    Input: job_id URL param
    Output: JSON {id, status, message, traceback}
    Details:
        Returns the stored error message and Celery task traceback (if available).
        Accessible without admin auth so the JS modal can fetch it directly.
        Only returns data for the requested job ID — no enumeration risk.
    """
    from flask_app import db
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
    Input: None (reads Flask-Login session)
    Output: 200 for authenticated admin, 403 otherwise
    Details:
        Used by Nginx auth_request to gate /admin/* routes at the proxy layer.
        Returns no body — only the status code is meaningful to Nginx.
    """
    if current_user.is_authenticated and current_user.role == "admin":
        return "", 200
    return "", 403


if __name__ == "__main__":
    pass
