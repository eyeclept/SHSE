"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Search blueprint. Home page, BM25 search results, per-user history,
    and user settings.
"""
# Imports
import logging
import math

from flask import Blueprint, render_template, request, session
from flask_login import current_user
from flask_app.services.opensearch import get_client
from flask_app.services.search import bm25_body_with_dorks
from flask_app.services.query_preprocessor import (
    strip_preamble, normalize, strip_stopwords, expand_synonyms,
)
from flask_app.services.stardict import build_definition_card

# Globals
search_bp = Blueprint("search", __name__)
logger = logging.getLogger(__name__)

_PAGE_SIZE = 10
_INDEX_NAME = "shse_pages"


# Functions
def _get_stats():
    """
    Input: None
    Output: dict with docs, services (count), service_names (list), last_crawl
    Details:
        Queries OpenSearch for index stats. Falls back to zeros on error.
    """
    try:
        client = get_client()
        count_resp = client.count(index=_INDEX_NAME)
        doc_count = count_resp.get("count", 0)

        agg_resp = client.search(index=_INDEX_NAME, body={
            "size": 0,
            "aggs": {
                "services": {"terms": {"field": "service_nickname", "size": 100}},
            },
        })
        buckets = agg_resp["aggregations"]["services"]["buckets"]
        service_names = [b["key"] for b in buckets]
        svc_count = len(service_names)

        last_resp = client.search(index=_INDEX_NAME, body={
            "size": 1, "sort": [{"crawled_at": "desc"}], "_source": ["crawled_at"],
        })
        hits = last_resp["hits"]["hits"]
        last_crawl = hits[0]["_source"].get("crawled_at", "")[:10] if hits else "never"
    except Exception:
        logger.warning("OpenSearch unavailable — returning zero stats", exc_info=True)
        doc_count = 0
        svc_count = 0
        service_names = []
        last_crawl = "unknown"

    return {
        "docs": doc_count,
        "services": svc_count,
        "service_names": service_names,
        "last_crawl": last_crawl,
    }


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
    raw = request.args.get("raw", "") in ("1", "true")
    filter_services = request.args.getlist("filter_service") or None
    sort = request.args.get("sort", "relevance")
    if sort not in ("relevance", "date_desc", "date_asc"):
        sort = "relevance"
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    from flask_app.config import Config
    if raw:
        # Bypass all optimizations; search exactly what the user typed
        search_q = q
        preprocessed_q = None
        rewritten_q = None
    else:
        preprocessed_q = expand_synonyms(strip_stopwords(normalize(strip_preamble(q)))) if q else q
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
    show_bm25_warning = False

    answer_card, ai_context = build_definition_card(q) if q else (None, None)

    if q:
        try:
            client = get_client()
            body = bm25_body_with_dorks(
                search_q, page=page, page_size=_PAGE_SIZE,
                highlight_tags=('<strong class="shse-hit">', "</strong>"),
                filter_services=filter_services,
                sort=sort,
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
            logger.warning("BM25 search failed", exc_info=True)

        # Semantic search runs asynchronously via HTMX (/api/semantic).
        # show_bm25_warning is only shown here if we can quickly determine
        # the LLM is not configured at all (no LLM_API_BASE set).
        show_bm25_warning = not bool(Config.LLM_API_BASE)

    return render_template(
        "results.html",
        q=q,
        preprocessed_q=preprocessed_q if preprocessed_q and preprocessed_q != q else None,
        rewritten_q=rewritten_q,
        raw=raw,
        raw_param="1" if raw else None,
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
        filter_services=filter_services or [],
        sort=sort,
        answer_card=answer_card,
        ai_context=ai_context,
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
        logger.warning("Failed to save search history", exc_info=True)


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
    Input: theme (radio) form POST
    Output: rendered settings page
    Details:
        Allows users to set theme preference, stored in the Flask session.
    """
    from flask import flash

    if request.method == "POST":
        theme = request.form.get("theme", "light")
        if theme in ("light", "dark"):
            session["theme"] = theme
        if "ai_summary_enabled" in request.form:
            session["ai_summary_enabled"] = request.form.get("ai_summary_enabled") == "1"
        flash("Settings saved.", "success")

    # Read admin's global AI summary setting for conditional display
    ai_summary_globally_enabled = True
    try:
        from flask_app import db
        from flask_app.models.system_setting import SystemSetting
        row = db.session.get(SystemSetting, "llm.ai_summary_enabled")
        ai_summary_globally_enabled = row is None or row.value != "0"
    except Exception:
        logger.warning("settings: could not read system_setting", exc_info=True)

    return render_template(
        "settings.html",
        current_theme=session.get("theme", "light"),
        ai_summary_globally_enabled=ai_summary_globally_enabled,
        ai_summary_user_enabled=session.get("ai_summary_enabled", True),
    )


@search_bp.route("/settings/clear-history", methods=["POST"])
def settings_clear_history():
    """Alias that settings.html posts to."""
    return history_clear()


@search_bp.route("/settings/password", methods=["POST"])
def settings_password():
    """
    Input: current_password, new_password, confirm_password (form POST)
    Output: 302 redirect on success; 400 with rendered settings page on error
    Details:
        Changes the current user's password. Requires current password to be correct.
    """
    from flask import flash, redirect, url_for, make_response
    from flask_app import db

    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))

    current_pw = request.form.get("current_password", "")
    new_pw = request.form.get("new_password", "")
    confirm_pw = request.form.get("confirm_password", "")

    if not current_user.check_password(current_pw):
        flash("Current password is incorrect.", "error")
        return make_response(
            render_template("settings.html", current_theme=session.get("theme", "light")), 400
        )
    if len(new_pw) < 8:
        flash("New password must be at least 8 characters.", "error")
        return make_response(
            render_template("settings.html", current_theme=session.get("theme", "light")), 400
        )
    if new_pw != confirm_pw:
        flash("New passwords do not match.", "error")
        return make_response(
            render_template("settings.html", current_theme=session.get("theme", "light")), 400
        )

    current_user.set_password(new_pw)
    db.session.commit()
    flash("Password changed successfully.", "success")
    return redirect(url_for("search.settings"))


if __name__ == "__main__":
    pass
