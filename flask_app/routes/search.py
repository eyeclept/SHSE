"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Search blueprint. Home page, BM25 search results, per-user history,
    and user settings.
"""
# Imports
import math

from flask import Blueprint, render_template, request
from flask_login import current_user
from flask_app.services.opensearch import get_client

# Globals
search_bp = Blueprint("search", __name__)

_PAGE_SIZE = 10
_INDEX_NAME = "shse_pages"


# Functions
def _get_stats():
    """
    Input: None
    Output: dict with docs, services, last_crawl
    Details:
        Queries OpenSearch for index stats. Falls back to zeros on error.
    """
    try:
        client = get_client()
        count_resp = client.count(index=_INDEX_NAME)
        doc_count = count_resp.get("count", 0)

        agg_resp = client.search(index=_INDEX_NAME, body={
            "size": 0,
            "aggs": {"services": {"cardinality": {"field": "service_nickname"}}},
        })
        svc_count = agg_resp["aggregations"]["services"]["value"]

        last_resp = client.search(index=_INDEX_NAME, body={
            "size": 1, "sort": [{"crawled_at": "desc"}], "_source": ["crawled_at"],
        })
        hits = last_resp["hits"]["hits"]
        last_crawl = hits[0]["_source"].get("crawled_at", "")[:10] if hits else "never"
    except Exception:
        doc_count = 0
        svc_count = 0
        last_crawl = "unknown"

    return {"docs": doc_count, "services": svc_count, "last_crawl": last_crawl}


@search_bp.route("/", methods=["GET"])
def home():
    """
    Input: None
    Output: rendered home.html with index stats
    Details:
        Landing page with search box and stat strip.
    """
    return render_template("home.html", stats=_get_stats())


@search_bp.route("/search", methods=["GET"])
def results():
    """
    Input: q (query string), tab, page
    Output: rendered results.html
    Details:
        Runs BM25 search with highlighting and facet aggregation.
        Saves query to search_history when a logged-in user searches.
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

    if q:
        try:
            client = get_client()
            body = {
                "from": (page - 1) * _PAGE_SIZE,
                "size": _PAGE_SIZE,
                "query": {"match": {"text": {"query": q, "fuzziness": "AUTO"}}},
                "highlight": {
                    "fields": {"text": {}},
                    "pre_tags": ['<strong class="shse-hit">'],
                    "post_tags": ["</strong>"],
                    "number_of_fragments": 2,
                    "fragment_size": 160,
                },
                "aggs": {
                    "by_service": {"terms": {"field": "service_nickname", "size": 20}},
                },
            }
            resp = client.search(index=_INDEX_NAME, body=body)
            took_ms = resp.get("took", 0)
            total = resp["hits"]["total"]["value"]
            page_count = max(1, math.ceil(total / _PAGE_SIZE))

            for h in resp["hits"]["hits"]:
                src = h.get("_source", {})
                hl = h.get("highlight", {})
                snippet = " … ".join(hl.get("text", [src.get("text", "")[:200]]))
                result_rows.append({
                    "id": h["_id"],
                    "title": src.get("title") or src.get("url", ""),
                    "url": src.get("url", ""),
                    "service": src.get("service_nickname", ""),
                    "service_label": src.get("service_nickname", ""),
                    "port": src.get("port", 80),
                    "crawled_at": (src.get("crawled_at") or "")[:10],
                    "content_type": src.get("content_type", ""),
                    "snippet_html": snippet,
                    "chunks": 1,
                    "vectorized": bool(src.get("vectorized", False)),
                })

            buckets = resp.get("aggregations", {}).get("by_service", {}).get("buckets", [])
            sources = [{"name": b["key"], "n": b["doc_count"]} for b in buckets]

            if q and current_user.is_authenticated:
                _save_history(q)

        except Exception:
            pass

    return render_template(
        "results.html",
        q=q,
        tab=tab,
        results=result_rows,
        total=total,
        took_ms=took_ms,
        page=page,
        page_count=page_count,
        tab_counts={"all": total, "docs": 0, "web": 0, "code": 0},
        related=[],
        vector_hits=[],
        keyword_chips=[],
        sources=sources,
        ai_summary=None,
        show_bm25_warning=False,
    )


def _save_history(query):
    """
    Input: query str
    Output: None
    Details:
        Writes one SearchHistory row for the logged-in user. Swallows errors.
    """
    try:
        from flask_app import db
        from flask_app.models.search_history import SearchHistory
        row = SearchHistory(user_id=current_user.id, query=query)
        db.session.add(row)
        db.session.commit()
    except Exception:
        pass


@search_bp.route("/history")
def history():
    """
    Input: None
    Output: rendered history page (stub)
    Details:
        Returns search history for the current user. Template pending Claude Design.
    """
    return render_template("search.html")


@search_bp.route("/settings", methods=["GET", "POST"])
def settings():
    """
    Input: ai_summary_enabled, llm_gen_model (form POST)
    Output: rendered settings page (stub)
    Details:
        Allows users to toggle AI summary and select the LLM generative model.
        Template pending Claude Design.
    """
    return render_template("settings.html")


if __name__ == "__main__":
    pass
