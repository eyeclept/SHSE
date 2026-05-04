"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for Epic 12 (Nginx): reverse proxy config validity and
    admin-check endpoint behaviour.
    Live proxy tests require the full Docker stack; those are skipped when
    the stack is not running. The admin-check unit tests run without Docker.
"""
# Imports
import os
from unittest.mock import MagicMock, patch

import pytest
import requests as _requests
from flask import Flask
from flask_app import db, login_manager

# Globals
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "templates")
_STATIC_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "static")
_NGINX_CONF = os.path.join(_PROJECT_ROOT, "nginx", "nginx.conf")
_HTTPS_BASE = "https://localhost:8443"


def _nginx_up():
    try:
        _requests.get(_HTTPS_BASE, verify=False, timeout=2)
        return True
    except Exception:
        return False


# Functions
def test_nginx_conf_contains_auth_request():
    """
    Input: nginx/nginx.conf file
    Output: file contains auth_request directive pointing to /api/admin-check
    Details:
        Verifies the Nginx config has the defence-in-depth admin restriction
        wired up correctly — no live Nginx required.
    """
    with open(_NGINX_CONF) as f:
        conf = f.read()
    assert "auth_request" in conf
    assert "/api/admin-check" in conf


def test_nginx_conf_contains_ssl_directives():
    """
    Input: nginx/nginx.conf file
    Output: file references ssl_certificate and ssl_certificate_key
    """
    with open(_NGINX_CONF) as f:
        conf = f.read()
    assert "ssl_certificate" in conf
    assert "ssl_certificate_key" in conf


def test_nginx_conf_has_proxy_pass_to_flask():
    """
    Input: nginx/nginx.conf file
    Output: file contains proxy_pass pointing at flask:5000
    """
    with open(_NGINX_CONF) as f:
        conf = f.read()
    assert "proxy_pass" in conf
    assert "flask:5000" in conf


# ── admin-check unit tests (no Docker required) ───────────────────────────

@pytest.fixture
def api_app():
    from flask_app.models.user import User                     # noqa: F401
    from flask_app.models.search_history import SearchHistory  # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget  # noqa: F401
    from flask_app.models.crawl_job import CrawlJob            # noqa: F401
    from flask_app.routes.api import api_bp
    from flask_app.routes.auth import auth_bp
    from flask_app.routes.search import search_bp
    from flask_app.routes.admin import admin_bp

    flask_app = Flask("test_nginx", template_folder=_TEMPLATE_DIR,
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
    flask_app.register_blueprint(api_bp)
    flask_app.register_blueprint(auth_bp)
    flask_app.register_blueprint(search_bp)
    flask_app.register_blueprint(admin_bp, url_prefix="/admin")
    with flask_app.app_context():
        db.create_all()
        yield flask_app


@pytest.fixture
def api_client(api_app):
    return api_app.test_client()


def test_admin_check_200_for_admin(api_app, api_client):
    """
    Input: GET /api/admin-check as authenticated admin
    Output: 200
    """
    from flask_app.models.user import User
    with api_app.app_context():
        u = User(username="nginxadmin", role="admin")
        u.set_password("pass")
        db.session.add(u)
        db.session.commit()
    api_client.post("/login", data={"username": "nginxadmin", "password": "pass"})
    r = api_client.get("/api/admin-check")
    assert r.status_code == 200


def test_admin_check_403_for_user(api_app, api_client):
    """
    Input: GET /api/admin-check as authenticated non-admin
    Output: 403
    """
    from flask_app.models.user import User
    with api_app.app_context():
        u = User(username="nginxuser", role="user")
        u.set_password("pass")
        db.session.add(u)
        db.session.commit()
    api_client.post("/login", data={"username": "nginxuser", "password": "pass"})
    r = api_client.get("/api/admin-check")
    assert r.status_code == 403


def test_admin_check_403_for_anonymous(api_client):
    """
    Input: GET /api/admin-check without session
    Output: 403
    """
    r = api_client.get("/api/admin-check")
    assert r.status_code == 403


# ── Live proxy tests (skipped when Nginx is not running) ──────────────────

@pytest.mark.skipif(not _nginx_up(), reason="Nginx not running — start docker compose")
def test_http_redirects_to_https():
    """
    Input: HTTP GET to Nginx at port 8888
    Output: 301 redirect to HTTPS
    Details:
        Verifies the plain-HTTP listener returns 301 rather than serving
        content directly or timing out. allow_redirects=False captures the
        redirect response without following it.
    """
    r = _requests.get("http://localhost:8888/", verify=False, timeout=5,
                      allow_redirects=False)
    assert r.status_code == 301


@pytest.mark.skipif(not _nginx_up(), reason="Nginx not running — start docker compose")
def test_https_proxy_forwards_to_flask():
    """
    Input: HTTPS GET to Nginx at port 8443
    Output: any response from Flask (proves Nginx is proxying, not blocking)
    Details:
        Verifies Nginx is proxying requests to Flask correctly. A 500 from a
        stale Flask container still means the proxy is working.
    """
    r = _requests.get(_HTTPS_BASE + "/", verify=False, timeout=5,
                      allow_redirects=True)
    # Any response that came through the proxy is acceptable — 502/504 would
    # mean Nginx couldn't reach Flask at all.
    assert r.status_code not in (502, 504)


@pytest.mark.skipif(not _nginx_up(), reason="Nginx not running — start docker compose")
def test_admin_restricted_at_nginx_level():
    """
    Input: unauthenticated HTTPS request to /admin/ via Nginx
    Output: 302, 403, or 401 — anything but a plain 200 (admin must not be open)
    """
    r = _requests.get(_HTTPS_BASE + "/admin/", verify=False, timeout=5,
                      allow_redirects=False)
    assert r.status_code != 200
