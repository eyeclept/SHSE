"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for Epic 10 (Search UI): search route, AI summary async endpoint,
    history page, login page, and registration page.
    Uses in-memory SQLite and mocked OpenSearch/LLM. No live services required.
"""
# Imports
import os
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
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
    Output: Flask test app with all blueprints and SQLite
    """
    from flask_app.models.user import User                     # noqa: F401
    from flask_app.models.search_history import SearchHistory  # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget  # noqa: F401
    from flask_app.models.crawl_job import CrawlJob            # noqa: F401
    from flask_app.routes.auth import auth_bp
    from flask_app.routes.search import search_bp
    from flask_app.routes.admin import admin_bp
    from flask_app.routes.api import api_bp

    flask_app = Flask("test_search_ui", template_folder=_TEMPLATE_DIR,
                      static_folder=_STATIC_DIR)
    flask_app.config.update({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "TESTING": True,
        "SECRET_KEY": "test",
        "SSO_ENABLED": False,
    })
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


def _empty_os():
    """Returns a mocked OpenSearch that returns zero results."""
    mc = MagicMock()
    mc.search.return_value = {
        "took": 1,
        "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []},
        "aggregations": {"by_service": {"buckets": []}},
    }
    mc.count.return_value = {"count": 0}
    return mc


# ── Search routes ─────────────────────────────────────────────────────────

def test_search_route_returns_bm25_results(client):
    """
    Input: GET /search?q=animal
    Output: 200 HTML with result data
    Details:
        Verifies the BM25 route renders the results page correctly.
    """
    fake_hit = {
        "_id": "abc", "_score": 1.5,
        "_source": {
            "title": "Animal", "url": "http://kiwix/Animal",
            "service_nickname": "kiwix", "port": 8082,
            "crawled_at": "2026-04-25T00:00:00",
            "content_type": "text/html",
            "text": "Animals are diverse eukaryotic organisms.",
            "vectorized": False,
        },
        "highlight": {"text": ["Animals are diverse eukaryotic organisms."]},
    }
    mc = MagicMock()
    mc.search.return_value = {
        "took": 3,
        "hits": {"total": {"value": 1, "relation": "eq"}, "hits": [fake_hit]},
        "aggregations": {"by_service": {"buckets": [{"key": "kiwix", "doc_count": 1}]}},
    }
    with patch("flask_app.routes.search.get_client", return_value=mc):
        r = client.get("/search?q=animal")
    assert r.status_code == 200
    assert b"Animal" in r.data


def test_search_empty_query_shows_empty_state(client):
    """
    Input: GET /search with no query
    Output: 200 with no OpenSearch call made
    """
    with patch("flask_app.routes.search.get_client") as mock_get:
        r = client.get("/search")
    assert r.status_code == 200
    mock_get.assert_not_called()


def test_search_opensearch_down_returns_empty(client):
    """
    Input: GET /search?q=test when OpenSearch is unreachable
    Output: 200 with empty results — no 500
    """
    with patch("flask_app.routes.search.get_client", side_effect=Exception("down")):
        r = client.get("/search?q=test")
    assert r.status_code == 200


# ── AI summary card ───────────────────────────────────────────────────────

def test_ai_summary_card_hidden_when_llm_unreachable(client):
    """
    Input: GET /api/semantic?q=test when LLM API is down
    Output: 200 HTML fragment with no ai_summary card
    Details:
        Patches semantic_results to return ([], None, True) — LLM unavailable.
        The rendered fragment should show the BM25 warning, not an AI summary.
    """
    with patch("flask_app.routes.api.semantic_results",
               return_value=([], None, True, [])):
        r = client.get("/api/semantic?q=test")
    assert r.status_code == 200
    assert b"AI summary" not in r.data


def test_ai_summary_card_shown_when_llm_available(client):
    """
    Input: GET /api/semantic?q=animal with working LLM mock
    Output: 200 HTML fragment containing 'AI summary'
    """
    fake_summary = {"html": "Animals are diverse organisms.", "sources": ["kiwix"]}
    fake_hits = [{"score": 0.9, "service": "kiwix", "url": "http://k/A",
                  "title": "A", "snippet": "text"}]

    with patch("flask_app.routes.api.semantic_results",
               return_value=(fake_hits, fake_summary, False, [])):
        r = client.get("/api/semantic?q=animal")
    assert r.status_code == 200
    assert b"AI summary" in r.data


# ── Search history ────────────────────────────────────────────────────────

def test_query_saved_to_history_after_authenticated_search(app, client):
    """
    Input: authenticated GET /search?q=history-test
    Output: SearchHistory row written for the logged-in user
    """
    from flask_app.models.user import User
    from flask_app.models.search_history import SearchHistory

    with app.app_context():
        u = User(username="histuser", role="user")
        u.set_password("pass")
        db.session.add(u)
        db.session.commit()

    client.post("/login", data={"username": "histuser", "password": "pass"})

    with patch("flask_app.routes.search.get_client", return_value=_empty_os()):
        client.get("/search?q=history-test")

    with app.app_context():
        row = db.session.query(SearchHistory).filter_by(query="history-test").first()
        assert row is not None


def test_history_page_lists_user_queries(app, client):
    """
    Input: GET /history after a logged-in user has searched
    Output: 200 HTML containing the past query
    """
    from flask_app.models.user import User
    from flask_app.models.search_history import SearchHistory

    with app.app_context():
        u = User(username="histviewer", role="user")
        u.set_password("pass")
        db.session.add(u)
        db.session.commit()
        db.session.add(SearchHistory(user_id=u.id, query="my-past-query"))
        db.session.commit()

    client.post("/login", data={"username": "histviewer", "password": "pass"})
    r = client.get("/history")
    assert r.status_code == 200
    assert b"my-past-query" in r.data


def test_history_page_requires_login(client):
    """
    Input: GET /history without a session
    Output: redirect to login (302)
    """
    r = client.get("/history")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


# ── Auth pages ────────────────────────────────────────────────────────────

def test_login_page_renders(client):
    """
    Input: GET /login
    Output: 200 HTML with 'Sign in' text
    """
    r = client.get("/login")
    assert r.status_code == 200
    assert b"Sign in" in r.data


def test_register_page_renders(client):
    """
    Input: GET /register
    Output: 200 HTML with 'Create account' or 'First-run setup'
    """
    r = client.get("/register")
    assert r.status_code == 200
    assert b"account" in r.data.lower() or b"setup" in r.data.lower()


def test_register_first_user_shows_admin_copy(app, client):
    """
    Input: GET /register when no users exist (is_first=True)
    Output: page mentions admin account creation
    """
    r = client.get("/register")
    assert r.status_code == 200
    assert b"admin" in r.data.lower()
