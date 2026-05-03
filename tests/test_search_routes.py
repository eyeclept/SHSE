"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for flask_app/routes/search.py: home(), results(), and _save_history().
    Uses in-memory SQLite and mocked OpenSearch. No live services required.

    Note: api.search() (tested in test_api.py) and search.results() have
    separate implementations. This file tests the search blueprint routes
    specifically.
"""
# Imports
import os
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask_login import login_user
from flask_app import db, login_manager

# Globals
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "templates")
_STATIC_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "static")


# Functions
@pytest.fixture
def app():
    """
    Input: None
    Output: Flask test app with search, auth, and admin blueprints
    Details:
        Full blueprint set is registered so url_for() calls in templates
        resolve without BuildError.
    """
    from flask_app.models.user import User                     # noqa: F401
    from flask_app.models.search_history import SearchHistory  # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget  # noqa: F401
    from flask_app.models.crawl_job import CrawlJob            # noqa: F401
    from flask_app.routes.auth import auth_bp
    from flask_app.routes.search import search_bp
    from flask_app.routes.admin import admin_bp
    from flask_app.routes.api import api_bp

    flask_app = Flask(
        "test_search_routes",
        template_folder=_TEMPLATE_DIR,
        static_folder=_STATIC_DIR,
    )
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    flask_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test"
    flask_app.config["SSO_ENABLED"] = False

    db.init_app(flask_app)
    login_manager.init_app(flask_app)

    flask_app.register_blueprint(auth_bp)
    flask_app.register_blueprint(search_bp)
    flask_app.register_blueprint(admin_bp, url_prefix="/admin")
    flask_app.register_blueprint(api_bp)

    with flask_app.app_context():
        db.create_all()
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _fake_os_search_response(hits=None, total=None, took=3, buckets=None):
    hits = hits or []
    return {
        "took": took,
        "hits": {
            "total": {"value": total if total is not None else len(hits), "relation": "eq"},
            "hits": hits,
        },
        "aggregations": {
            "by_service": {"buckets": buckets or []},
        },
    }


# ── home() ────────────────────────────────────────────────────────────────

def test_home_returns_200(client):
    """
    Input: GET /
    Output: 200 HTML response
    Details:
        home() renders home.html. OpenSearch is mocked to return empty stats.
    """
    mock_client = MagicMock()
    mock_client.count.return_value = {"count": 0}
    mock_client.search.side_effect = [
        {"aggregations": {"services": {"value": 0}}},
        {"hits": {"hits": []}},
    ]
    with patch("flask_app.routes.search.get_client", return_value=mock_client):
        r = client.get("/")
    assert r.status_code == 200
    assert b"Search" in r.data


def test_home_passes_stats_to_template(client):
    """
    Input: GET / with mocked OpenSearch returning real counts
    Output: 200 response whose body includes the document count
    Details:
        Verifies _get_stats() queries OpenSearch and the result is rendered.
    """
    mock_client = MagicMock()
    mock_client.count.return_value = {"count": 12345}
    mock_client.search.side_effect = [
        {"aggregations": {"services": {"buckets": [
            {"key": "homelab-docs"}, {"key": "gitea"},
            {"key": "kiwix"}, {"key": "wiki"},
        ]}}},
        {"hits": {"hits": [{"_source": {"crawled_at": "2026-04-25T00:00:00"}}]}},
    ]
    with patch("flask_app.routes.search.get_client", return_value=mock_client):
        r = client.get("/")
    assert r.status_code == 200
    assert b"12,345" in r.data


def test_home_opensearch_unreachable_returns_zeros(client):
    """
    Input: GET / when OpenSearch raises
    Output: 200 with zero stats — no crash
    Details:
        _get_stats() catches all exceptions and falls back to zeros.
    """
    with patch("flask_app.routes.search.get_client", side_effect=Exception("down")):
        r = client.get("/")
    assert r.status_code == 200


# ── results() ─────────────────────────────────────────────────────────────

_SEMANTIC_PATCH = "flask_app.routes.search.semantic_results"
_SEMANTIC_EMPTY = ([], None, False)


def test_results_empty_query_returns_200(client):
    """
    Input: GET /search with no q param
    Output: 200 HTML with empty-state content; no OpenSearch call
    Details:
        results() skips the OpenSearch call when q is blank.
    """
    with patch("flask_app.routes.search.get_client") as mock_get:
        r = client.get("/search")
    assert r.status_code == 200
    mock_get.assert_not_called()


def test_results_returns_bm25_results(client):
    """
    Input: GET /search?q=animal
    Output: 200 HTML containing result title text
    Details:
        Verifies results() passes BM25 hits to the template correctly.
    """
    fake_hit = {
        "_id": "abc",
        "_score": 1.5,
        "_source": {
            "title": "Animal",
            "url": "http://kiwix/Animal",
            "service_nickname": "kiwix",
            "port": 8082,
            "crawled_at": "2026-04-25T00:00:00",
            "content_type": "text/html",
            "text": "Animals are diverse organisms.",
            "vectorized": False,
        },
        "highlight": {"text": ["Animals are diverse organisms."]},
    }
    mock_client = MagicMock()
    mock_client.search.return_value = _fake_os_search_response([fake_hit], total=1)

    with patch("flask_app.routes.search.get_client", return_value=mock_client):
        r = client.get("/search?q=animal")

    assert r.status_code == 200
    assert b"Animal" in r.data


def test_results_pagination_offset(client):
    """
    Input: GET /search?q=test&page=3
    Output: OpenSearch called with from=20 (page 3, page_size 10)
    Details:
        Verifies the from/size calculation in results() uses the correct offset.
    """
    mock_client = MagicMock()
    mock_client.search.return_value = _fake_os_search_response([], total=50)

    with patch("flask_app.routes.search.get_client", return_value=mock_client):
        r = client.get("/search?q=test&page=3")

    assert r.status_code == 200
    call_body = mock_client.search.call_args.kwargs["body"]
    assert call_body["from"] == 20
    assert call_body["size"] == 10


def test_results_bad_page_param_does_not_crash(client):
    """
    Input: GET /search?q=test&page=notanumber
    Output: 200, page defaults to 1
    Details:
        Verifies the ValueError guard on int(page) is in place.
    """
    mock_client = MagicMock()
    mock_client.search.return_value = _fake_os_search_response([])

    with patch("flask_app.routes.search.get_client", return_value=mock_client):
        r = client.get("/search?q=test&page=notanumber")

    assert r.status_code == 200


def test_results_opensearch_unreachable_returns_empty(client):
    """
    Input: GET /search?q=test when OpenSearch raises
    Output: 200 with empty results — no 500 error
    """
    with patch("flask_app.routes.search.get_client", side_effect=Exception("down")):
        r = client.get("/search?q=test")
    assert r.status_code == 200


# ── _save_history() ───────────────────────────────────────────────────────

def test_save_history_writes_row_for_authenticated_user(app, client):
    """
    Input: logged-in user performs GET /search?q=history-test
    Output: a SearchHistory row is written to the DB
    Details:
        _save_history() is called inside results() when the user is
        authenticated. Verifies the row exists after the request.
    """
    from flask_app.models.user import User
    from flask_app.models.search_history import SearchHistory

    with app.app_context():
        user = User(username="searcher", role="user")
        user.set_password("pass")
        db.session.add(user)
        db.session.commit()

    client.post("/login", data={"username": "searcher", "password": "pass"})

    mock_client = MagicMock()
    mock_client.search.return_value = _fake_os_search_response([])

    with patch("flask_app.routes.search.get_client", return_value=mock_client):
        r = client.get("/search?q=history-test")

    assert r.status_code == 200

    with app.app_context():
        row = db.session.query(SearchHistory).filter_by(query="history-test").first()
        assert row is not None
        assert row.query == "history-test"


def test_save_history_not_written_for_anonymous_user(app, client):
    """
    Input: unauthenticated GET /search?q=anon-test
    Output: no SearchHistory row written; request completes without error
    """
    from flask_app.models.search_history import SearchHistory

    mock_client = MagicMock()
    mock_client.search.return_value = _fake_os_search_response([])

    with patch("flask_app.routes.search.get_client", return_value=mock_client):
        r = client.get("/search?q=anon-test")

    assert r.status_code == 200

    with app.app_context():
        count = db.session.query(SearchHistory).filter_by(query="anon-test").count()
        assert count == 0


# ── Query rewriter ─────────────────────────────────────────────────────────

def test_results_uses_rewritten_query_when_enabled(app, client):
    """
    Input: GET /search?q=please+find+server+config with QUERY_REWRITE_ENABLED=true
    Output: OpenSearch called with the rewritten query, not the raw input
    Details:
        When QUERY_REWRITE_ENABLED is true and rewrite_query returns a different
        string, the search route must use the rewritten query for the OpenSearch call.
    """
    mock_client = MagicMock()
    mock_client.search.return_value = _fake_os_search_response([])

    with app.app_context():
        app.config["QUERY_REWRITE_ENABLED"] = True

    with patch("flask_app.routes.search.get_client", return_value=mock_client), \
         patch("flask_app.config.Config.QUERY_REWRITE_ENABLED", True), \
         patch("flask_app.services.llm.rewrite_query", return_value="server config") as rw_mock:
        r = client.get("/search?q=please+find+server+config")

    assert r.status_code == 200
    rw_mock.assert_called_once()
    call_body = mock_client.search.call_args.kwargs["body"]
    assert call_body["query"]["multi_match"]["query"] == "server config"


def test_results_skips_rewriter_when_disabled(app, client):
    """
    Input: GET /search?q=server with QUERY_REWRITE_ENABLED=false (default)
    Output: rewrite_query is never called; OpenSearch receives preprocessed query
    Details:
        When QUERY_REWRITE_ENABLED is false, the rewriter is not invoked.
    """
    mock_client = MagicMock()
    mock_client.search.return_value = _fake_os_search_response([])

    with patch("flask_app.routes.search.get_client", return_value=mock_client), \
         patch("flask_app.config.Config.QUERY_REWRITE_ENABLED", False), \
         patch("flask_app.services.llm.rewrite_query") as rw_mock:
        r = client.get("/search?q=server")

    assert r.status_code == 200
    rw_mock.assert_not_called()


def test_results_shows_rewriter_annotation(app, client):
    """
    Input: GET /search?q=please+tell+me+about+dns with QUERY_REWRITE_ENABLED=true
    Output: response body contains "AI rewrote query to"
    Details:
        When rewritten_q differs from preprocessed_q, the annotation block in
        results.html must be present in the rendered HTML.
    """
    mock_client = MagicMock()
    mock_client.search.return_value = _fake_os_search_response([])

    with patch("flask_app.routes.search.get_client", return_value=mock_client), \
         patch("flask_app.config.Config.QUERY_REWRITE_ENABLED", True), \
         patch("flask_app.services.llm.rewrite_query", return_value="dns lookup"):
        r = client.get("/search?q=please+tell+me+about+dns")

    assert r.status_code == 200
    assert b"AI rewrote query to" in r.data


def test_results_raw_mode_skips_preprocessing(client):
    """
    Input: GET /search?q=please+find+server&raw=1
    Output: OpenSearch called with the raw query, not the preprocessed form
    Details:
        When raw=1 is set, the preprocessing pipeline must be bypassed entirely.
    """
    mock_client = MagicMock()
    mock_client.search.return_value = _fake_os_search_response([])

    with patch("flask_app.routes.search.get_client", return_value=mock_client), \
         patch("flask_app.routes.search.strip_preamble") as spy_pre:
        r = client.get("/search?q=please+find+server&raw=1")

    assert r.status_code == 200
    spy_pre.assert_not_called()
    call_body = mock_client.search.call_args.kwargs["body"]
    assert call_body["query"]["multi_match"]["query"] == "please find server"


def test_results_raw_mode_shows_exact_notice(client):
    """
    Input: GET /search?q=test+query&raw=1
    Output: response body contains "Searching for exactly" and "Use optimizations" link
    """
    mock_client = MagicMock()
    mock_client.search.return_value = _fake_os_search_response([])

    with patch("flask_app.routes.search.get_client", return_value=mock_client):
        r = client.get("/search?q=test+query&raw=1")

    assert r.status_code == 200
    assert b"Searching for exactly" in r.data
    assert b"Use optimizations" in r.data


def test_results_shows_exact_link_when_preprocessed(client):
    """
    Input: GET /search?q=please+find+server (preprocessing changes query)
    Output: "Search for exactly" link appears in the annotation
    """
    mock_client = MagicMock()
    mock_client.search.return_value = _fake_os_search_response([])

    with patch("flask_app.routes.search.get_client", return_value=mock_client), \
         patch("flask_app.routes.search.strip_preamble", return_value="find server"), \
         patch("flask_app.routes.search.normalize", return_value="find server"), \
         patch("flask_app.routes.search.strip_stopwords", return_value="server"), \
         patch("flask_app.routes.search.expand_synonyms", return_value="server"):
        r = client.get("/search?q=please+find+server")

    assert r.status_code == 200
    assert b"Search for exactly" in r.data
    assert b"raw=1" in r.data


def test_results_no_annotation_when_rewriter_disabled(client):
    """
    Input: GET /search?q=dns with QUERY_REWRITE_ENABLED=false
    Output: "AI rewrote query to" not in response body
    Details:
        When the rewriter is disabled, the annotation must be absent.
    """
    mock_client = MagicMock()
    mock_client.search.return_value = _fake_os_search_response([])

    with patch("flask_app.routes.search.get_client", return_value=mock_client), \
         patch("flask_app.config.Config.QUERY_REWRITE_ENABLED", False):
        r = client.get("/search?q=dns")

    assert r.status_code == 200
    assert b"AI rewrote query to" not in r.data


# ── Epic 9c: vector_hits in template context ───────────────────────────────

def test_vector_hits_in_context(app, client):
    """
    Input: GET /search?q=server with get_embedding mocked to return a vector
    Output: template context contains a 'vector_hits' key
    Details:
        Semantic results are fetched asynchronously via HTMX (/api/semantic),
        so search.results() always passes vector_hits=[] to the template.
        This test confirms the key is present in the context (even as an empty
        list) regardless of LLM availability — the HTMX rail is what populates
        it at render time.
    """
    from flask import template_rendered

    recorded = []

    def _record(sender, template, context, **_extra):
        recorded.append((template.name, context))

    mock_client = MagicMock()
    mock_client.search.return_value = _fake_os_search_response([])

    template_rendered.connect(_record, app)
    try:
        with patch("flask_app.routes.search.get_client", return_value=mock_client), \
             patch("flask_app.services.llm.get_embedding", return_value=[0.1] * 768):
            r = client.get("/search?q=server")
    finally:
        template_rendered.disconnect(_record, app)

    assert r.status_code == 200
    results_contexts = [ctx for name, ctx in recorded if name == "results.html"]
    assert results_contexts, "results.html was not rendered"
    assert "vector_hits" in results_contexts[0]
