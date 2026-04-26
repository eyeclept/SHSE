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

from flask import Blueprint, render_template, request, session
from flask_login import current_user
from flask_app.services.opensearch import get_client
from flask_app.services.search import bm25_body

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
        Runs BM25 multi_match search with typo tolerance and highlighting.
        When the LLM API is available and AI summary is enabled, also runs
        vector search and generates an AI summary card.
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
    show_bm25_warning = False

    if q:
        try:
            client = get_client()
            body = bm25_body(
                q, page=page, page_size=_PAGE_SIZE,
                highlight_tags=('<strong class="shse-hit">', "</strong>"),
            )
            resp = client.search(index=_INDEX_NAME, body=body)
            took_ms = resp.get("took", 0)
            total = resp["hits"]["total"]["value"]
            page_count = max(1, math.ceil(total / _PAGE_SIZE))

            for h in resp["hits"]["hits"]:
                src = h.get("_source", {})
                hl = h.get("highlight", {})
                title_frags = hl.get("title", [])
                text_frags = hl.get("text", [src.get("text", "")[:200]])
                snippet = " … ".join(title_frags + text_frags) if title_frags else " … ".join(text_frags)
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

            if current_user.is_authenticated:
                _save_history(q)

        except Exception:
            pass

        # Semantic search runs asynchronously via HTMX (/api/semantic).
        # show_bm25_warning is only shown here if we can quickly determine
        # the LLM is not configured at all (no LLM_API_BASE set).
        from flask_app.config import Config
        show_bm25_warning = not bool(Config.LLM_API_BASE)

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
        show_bm25_warning=show_bm25_warning,
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
    Input: q (optional filter)
    Output: rendered history page
    Details:
        Returns search history for the current logged-in user, newest first.
        Unauthenticated users are redirected to login.
    """
    from flask_login import login_required
    from flask import redirect, url_for
    from flask_app import db
    from flask_app.models.search_history import SearchHistory

    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))

    q_filter = request.args.get("q", "").strip()
    query = (
        db.session.query(SearchHistory)
        .filter_by(user_id=current_user.id)
        .order_by(SearchHistory.timestamp.desc())
        .limit(200)
    )
    rows = [
        {"q": r.query, "when": str(r.timestamp)[:16] if r.timestamp else "—", "results": None}
        for r in query.all()
        if not q_filter or q_filter.lower() in r.query.lower()
    ]
    return render_template("history.html", history=rows, q=q_filter)


@search_bp.route("/history/clear", methods=["POST"])
def history_clear():
    """
    Input: None
    Output: redirect to history page
    Details:
        Deletes all search history rows for the current user.
    """
    from flask import redirect
    from flask_app import db
    from flask_app.models.search_history import SearchHistory

    if not current_user.is_authenticated:
        from flask import url_for
        return redirect(url_for("auth.login"))
    db.session.query(SearchHistory).filter_by(user_id=current_user.id).delete()
    db.session.commit()
    from flask import flash, url_for
    flash("Search history cleared.", "success")
    return redirect(url_for("search.history"))


@search_bp.route("/history/_filter")
def history_filter():
    """
    Input: q (filter string) — HTMX request
    Output: rendered history list partial
    """
    from flask_app import db
    from flask_app.models.search_history import SearchHistory
    from flask import url_for

    if not current_user.is_authenticated:
        return ""
    q_filter = request.args.get("q", "").strip()
    rows = [
        {"q": r.query, "when": str(r.timestamp)[:16] if r.timestamp else "—", "results": None}
        for r in (
            db.session.query(SearchHistory)
            .filter_by(user_id=current_user.id)
            .order_by(SearchHistory.timestamp.desc())
            .limit(200)
            .all()
        )
        if not q_filter or q_filter.lower() in r.query.lower()
    ]
    return render_template("history.html", history=rows, q=q_filter)


@search_bp.route("/settings", methods=["GET", "POST"])
def settings():
    """
    Input: ai_summary_enabled (form POST)
    Output: rendered settings page
    Details:
        Allows users to toggle AI summary. Preference stored in session.
    """
    from flask import flash

    if request.method == "POST":
        enabled = request.form.get("ai_summary_enabled") == "on"
        session["ai_summary_enabled"] = enabled
        flash("Settings saved.", "success")

    class _FakeForm:
        class ai_summary_enabled:
            name = "ai_summary_enabled"
            id = "ai_summary_enabled"
            data = session.get("ai_summary_enabled", True)

    return render_template("settings.html", user=current_user, form=_FakeForm(), settings={})


@search_bp.route("/settings/clear-history", methods=["POST"])
def settings_clear_history():
    """Alias that settings.html posts to."""
    return history_clear()


@search_bp.route("/settings/password", methods=["GET"])
def settings_password():
    """Stub for password change modal — returns empty fragment."""
    return ""


if __name__ == "__main__":
    pass
