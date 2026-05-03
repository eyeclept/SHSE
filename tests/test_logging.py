"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for Epic 9f — Logging and Observability.
    Verifies that key failure paths emit WARNING or ERROR log records rather
    than silently swallowing exceptions. Uses assertLogs. No live services.
"""
# Imports
import os
import unittest
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask_app import db, login_manager

# Globals
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "templates")
_STATIC_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "static")

_TC = unittest.TestCase()


# Functions
@pytest.fixture
def app():
    """
    Input: None
    Output: Flask test app with all blueprints registered, SQLite in-memory
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
        "test_logging",
        template_folder=_TEMPLATE_DIR,
        static_folder=_STATIC_DIR,
    )
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    flask_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test"
    flask_app.config["SSO_ENABLED"] = False
    flask_app.config["PROPAGATE_EXCEPTIONS"] = False

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


# ── _get_stats ────────────────────────────────────────────────────────────────

def test_get_stats_logs_warning_on_opensearch_failure(app):
    """_get_stats() must emit a WARNING when OpenSearch is unreachable."""
    from flask_app.routes.search import _get_stats

    with app.app_context():
        with app.test_request_context("/"):
            with patch("flask_app.routes.search.get_client", side_effect=Exception("refused")):
                with _TC.assertLogs("flask_app.routes.search", level="WARNING") as cm:
                    result = _get_stats()
    assert result["docs"] == 0
    assert any("OpenSearch" in msg or "stats" in msg for msg in cm.output)


# ── search results BM25 ───────────────────────────────────────────────────────

def test_bm25_search_logs_warning_on_failure(client):
    """GET /search?q=x must emit a WARNING when the OpenSearch call raises."""
    with patch("flask_app.routes.search.get_client", side_effect=Exception("down")):
        with _TC.assertLogs("flask_app.routes.search", level="WARNING") as cm:
            resp = client.get("/search?q=hello")
    assert resp.status_code == 200
    assert any("BM25" in msg or "search" in msg.lower() for msg in cm.output)


# ── _save_history ─────────────────────────────────────────────────────────────

def test_save_history_logs_warning_on_db_failure(app):
    """_save_history() must emit WARNING when db.session.commit() raises."""
    from flask_app.routes.search import _save_history
    from flask_app.models.user import User
    from flask_login import login_user

    with app.app_context():
        user = User(username="log_user", role="user")
        user.set_password("password1")
        db.session.add(user)
        db.session.commit()

        with app.test_request_context("/"):
            login_user(user)
            # db is imported locally inside _save_history from flask_app;
            # patch at the source module level so the import picks up the mock.
            with patch("flask_app.db.session") as mock_session:
                mock_session.commit.side_effect = Exception("disk full")
                with _TC.assertLogs("flask_app.routes.search", level="WARNING") as cm:
                    _save_history("test query")
    assert any("history" in msg.lower() for msg in cm.output)


# ── api stats ─────────────────────────────────────────────────────────────────

def test_api_stats_logs_warning_on_opensearch_failure(client):
    """GET /api/stats must emit WARNING and return zeros when OpenSearch is down."""
    with patch("flask_app.routes.api.get_client", side_effect=Exception("unreachable")):
        with _TC.assertLogs("flask_app.routes.api", level="WARNING") as cm:
            resp = client.get("/api/stats")
    assert resp.status_code == 200
    assert resp.get_json()["docs"] == 0
    assert any("stats" in msg.lower() or "OpenSearch" in msg for msg in cm.output)


# ── api search ────────────────────────────────────────────────────────────────

def test_api_bm25_logs_warning_on_failure(client):
    """GET /api/search must emit WARNING when the BM25 OpenSearch call fails."""
    with patch("flask_app.routes.api.get_client", side_effect=Exception("unreachable")):
        with patch("flask_app.routes.api.semantic_results", return_value=([], None, False, [])):
            with _TC.assertLogs("flask_app.routes.api", level="WARNING") as cm:
                resp = client.get("/api/search?q=hello")
    assert resp.status_code == 200
    assert any("BM25" in msg or "search" in msg.lower() for msg in cm.output)


if __name__ == "__main__":
    pass
