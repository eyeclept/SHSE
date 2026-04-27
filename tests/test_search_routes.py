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
