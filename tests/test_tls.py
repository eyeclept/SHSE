"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for Epic 13 (TLS): per-target TLS bypass, global TLS flag,
    and admin dashboard TLS warning banner.
    No live services required.
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
    """Flask test app with all blueprints and SQLite."""
    from flask_app.models.user import User                     # noqa: F401
    from flask_app.models.search_history import SearchHistory  # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget  # noqa: F401
    from flask_app.models.crawl_job import CrawlJob            # noqa: F401
    from flask_app.routes.auth import auth_bp
    from flask_app.routes.search import search_bp
    from flask_app.routes.admin import admin_bp
    from flask_app.routes.api import api_bp

    flask_app = Flask("test_tls", template_folder=_TEMPLATE_DIR,
                      static_folder=_STATIC_DIR)
    flask_app.config.update({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "TESTING": True,
        "SECRET_KEY": "test",
        "SSO_ENABLED": False,
        "PROPAGATE_EXCEPTIONS": False,
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
def admin_client(app):
    """Authenticated admin test client."""
    from flask_app.models.user import User
    with app.app_context():
        u = User(username="tlsadmin", role="admin")
        u.set_password("pass")
        db.session.add(u)
        db.session.commit()
    c = app.test_client()
    c.post("/login", data={"username": "tlsadmin", "password": "pass"})
    return c


# ── Per-target TLS bypass ──────────────────────────────────────────────────

def test_fetch_page_text_passes_tls_verify_false():
    """
    Input: _fetch_page_text called with tls_verify=False
    Output: requests.get is called with verify=False
    Details:
        Verifies the per-target TLS bypass is forwarded to the HTTP request.
    """
    from flask_app.services.nutch import _fetch_page_text

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.headers = {"Content-Type": "text/html"}
    mock_resp.text = "<html><body><p>Hello</p></body></html>"

    with patch("flask_app.services.nutch.requests.get", return_value=mock_resp) as mock_get:
        _fetch_page_text("http://internal.lab/page", tls_verify=False)

    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs.get("verify") is False


def test_fetch_page_text_passes_tls_verify_true():
    """
    Input: _fetch_page_text called with tls_verify=True (default)
    Output: requests.get is called with verify=True
    """
    from flask_app.services.nutch import _fetch_page_text

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.headers = {"Content-Type": "text/html"}
    mock_resp.text = "<html><body><p>Hello</p></body></html>"

    with patch("flask_app.services.nutch.requests.get", return_value=mock_resp) as mock_get:
        _fetch_page_text("http://external.lab/page", tls_verify=True)

    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs.get("verify") is True


def test_nutch_crawl_propagates_tls_verify_to_page_fetch(app):
    """
    Input: CrawlerTarget with tls_verify=False processed by _nutch_crawl
    Output: _fetch_page_text is called with tls_verify=False
    Details:
        Verifies that the per-target tls_verify flag flows from the
        CrawlerTarget model through the crawl pipeline to the page fetch.
    """
    from flask_app.models.crawler_target import CrawlerTarget
    from celery_worker.tasks.crawl import _nutch_crawl

    target = CrawlerTarget(
        nickname="tls-bypass-svc",
        target_type="service",
        url="internal.lab",
        port=443,
        service="https",
        route="/",
        tls_verify=False,
    )

    fake_urls = ["https://internal.lab/page"]

    with patch("celery_worker.tasks.crawl._discover_urls",
               return_value=fake_urls), \
         patch("celery_worker.tasks.crawl._fetch_page_text",
               return_value="page text") as fetch_mock, \
         patch("celery_worker.tasks.crawl.index_document"), \
         patch("celery_worker.tasks.crawl.delete_stale"):
        _nutch_crawl(target)

    fetch_mock.assert_called_once()
    call = fetch_mock.call_args
    # tls_verify may be positional or keyword — check all args
    all_args = list(call.args) + list(call.kwargs.values())
    assert False in all_args, f"tls_verify=False not found in call args: {call}"


# ── Global TLS bypass flag ─────────────────────────────────────────────────

def test_global_tls_flag_disables_session_verify():
    """
    Input: INTERNAL_TLS_VERIFY=false in environment
    Output: get_session() returns a session with verify=False
    Details:
        Verifies the global flag flows through get_session() to all
        Nutch REST API calls made in that session.
    """
    from flask_app.services.nutch import get_session
    with patch.dict("os.environ", {"INTERNAL_TLS_VERIFY": "false"}):
        session = get_session()
    assert session.verify is False


def test_global_tls_flag_true_keeps_session_verify():
    """
    Input: INTERNAL_TLS_VERIFY=true (default) in environment
    Output: get_session() returns a session with verify=True
    """
    from flask_app.services.nutch import get_session
    with patch.dict("os.environ", {"INTERNAL_TLS_VERIFY": "true"}):
        session = get_session()
    assert session.verify is True


# ── TLS warning banner ─────────────────────────────────────────────────────

def test_tls_warning_banner_shown_when_target_has_verify_false(app, admin_client):
    """
    Input: GET /admin/ when a target exists with tls_verify=False
    Output: 200 HTML containing 'TLS verification disabled' warning
    """
    from flask_app.models.crawler_target import CrawlerTarget

    with app.app_context():
        t = CrawlerTarget(
            nickname="no-verify-svc",
            target_type="service",
            url="self-signed.lab",
            tls_verify=False,
        )
        db.session.add(t)
        db.session.commit()

    with patch("flask_app.routes.admin._check_services",
               return_value={s: {"status": "up", "latency_ms": 1, "message": None}
                             for s in ("opensearch", "nutch", "llm_api", "redis", "mariadb")}), \
         patch("flask_app.services.opensearch.get_client") as mock_os:
        mock_os.return_value.count.return_value = {"count": 0}
        mock_os.return_value.search.side_effect = [
            {"aggregations": {"svc": {"value": 0}, "vectorized": {"doc_count": 0}}},
            {"hits": {"hits": []}},
        ]
        r = admin_client.get("/admin/")

    assert r.status_code == 200
    assert b"TLS verification disabled" in r.data


def test_tls_warning_banner_absent_when_all_targets_verify(app, admin_client):
    """
    Input: GET /admin/ when all targets have tls_verify=True
    Output: 200 HTML without TLS warning
    """
    from flask_app.models.crawler_target import CrawlerTarget

    with app.app_context():
        t = CrawlerTarget(
            nickname="verified-svc",
            target_type="service",
            url="verified.lab",
            tls_verify=True,
        )
        db.session.add(t)
        db.session.commit()

    with patch("flask_app.routes.admin._check_services",
               return_value={s: {"status": "up", "latency_ms": 1, "message": None}
                             for s in ("opensearch", "nutch", "llm_api", "redis", "mariadb")}), \
         patch("flask_app.services.opensearch.get_client") as mock_os:
        mock_os.return_value.count.return_value = {"count": 0}
        mock_os.return_value.search.side_effect = [
            {"aggregations": {"svc": {"value": 0}, "vectorized": {"doc_count": 0}}},
            {"hits": {"hits": []}},
        ]
        r = admin_client.get("/admin/")

    assert r.status_code == 200
    assert b"TLS verification disabled" not in r.data
