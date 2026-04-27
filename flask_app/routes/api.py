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
import math

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user
from flask_app.services.opensearch import get_client
from flask_app.services.search import bm25_body, semantic_results

# Globals
api_bp = Blueprint("api", __name__, url_prefix="/api")

_INDEX_NAME = "shse_pages"
_PAGE_SIZE = 10


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
            body = bm25_body(q, page=page, page_size=_PAGE_SIZE)
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
            pass

        # Semantic search + AI summary
        vector_hits, ai_summary, show_bm25_warning, _chips = semantic_results(q)

    return jsonify({
        "q": q,
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
        return jsonify({"docs": 0, "services": 0, "last_crawl": None})


@api_bp.route("/semantic")
def semantic():
    """
    Input: q (query string)
    Output: HTML fragment replacing the semantic rail aside element
    Details:
        Called by HTMX on the results page after BM25 results have rendered.
        Runs vector search and generates an AI summary. Returns a complete
        <aside> element that HTMX swaps in place of the loading placeholder.
        Returns an empty aside when the LLM API is unavailable.
    """
    q = request.args.get("q", "").strip()
    if not q:
        return "<aside></aside>"

    vector_hits, ai_summary, show_bm25_warning, keyword_chips = semantic_results(q)
    return render_template(
        "_semantic_rail.html",
        q=q,
        vector_hits=vector_hits,
        ai_summary=ai_summary,
        show_bm25_warning=show_bm25_warning,
        keyword_chips=keyword_chips,
    )


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
            pass
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
