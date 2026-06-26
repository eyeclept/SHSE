"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Security tests for Epic 20. Validates session cookie flags, access control,
    configuration hygiene, Jinja2 auto-escape, and unauthenticated POST rejection.
"""
# Imports
import os
import pytest
from flask import Flask
from flask_app import db, login_manager, oauth
from flask_app.models.user import User

# Globals
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "templates")
_STATIC_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "static")

# Functions
@pytest.fixture(autouse=True)
def _writable_log_dir(tmp_path, monkeypatch):
    """
    Input: tmp_path, monkeypatch fixtures
    Output: None — sets SHSE_LOG_DIR to a writable temp dir for every test here
    Details:
        The tests that call the real create_app() construct a RotatingFileHandler
        on <repo>/logs/flask.log. On the app VM that file is owned by the root
        container, so a host-user pytest run hits PermissionError. Redirect the
        log dir to a per-test writable path so these tests pass regardless of who
        owns the repo's logs/ directory.
    """
    monkeypatch.setenv("SHSE_LOG_DIR", str(tmp_path))


@pytest.fixture
def secure_app():
    """
    Input: None
    Output: Flask test app with in-memory SQLite and security-relevant config
    Details:
        Minimal app using a non-default SECRET_KEY so tests can distinguish
        between the weak-default and a proper key. Session cookie flags
        are set to the values we expect in production.
    """
    from flask_app.models.search_history import SearchHistory          # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget          # noqa: F401
    from flask_app.models.crawl_job import CrawlJob                    # noqa: F401
    from flask_app.models.password_reset_token import PasswordResetToken  # noqa: F401
    from flask_app.models.webauthn_credential import WebAuthnCredential   # noqa: F401
    from flask_app.models.system_setting import SystemSetting          # noqa: F401

    from flask_app.routes.auth import auth_bp
    from flask_app.routes.search import search_bp
    from flask_app.routes.admin import admin_bp
    from flask_app.routes.api import api_bp

    test_app = Flask("test_security", template_folder=_TEMPLATE_DIR, static_folder=_STATIC_DIR)
    test_app.config["TESTING"] = True
    test_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    test_app.config["SECRET_KEY"] = "test-only-secret-not-default"
    test_app.config["SESSION_COOKIE_HTTPONLY"] = True
    test_app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    test_app.config["WTF_CSRF_ENABLED"] = False  # disabled in tests; see SEC-003 for remediation
    db.init_app(test_app)
    login_manager.init_app(test_app)
    login_manager.login_view = "auth.login"
    test_app.register_blueprint(auth_bp)
    test_app.register_blueprint(search_bp)
    test_app.register_blueprint(admin_bp, url_prefix="/admin")
    test_app.register_blueprint(api_bp)

    with test_app.app_context():
        db.create_all()
        yield test_app
        db.drop_all()


def test_session_cookie_httponly_flag(secure_app):
    """
    Input: secure_app fixture
    Output: None
    Details:
        Confirms SESSION_COOKIE_HTTPONLY is True in app config so that the
        session cookie cannot be accessed from JavaScript.
    """
    assert secure_app.config.get("SESSION_COOKIE_HTTPONLY") is True


def test_session_cookie_samesite_flag(secure_app):
    """
    Input: secure_app fixture
    Output: None
    Details:
        Confirms SESSION_COOKIE_SAMESITE is set to Lax or Strict (see SEC-002).
    """
    samesite = secure_app.config.get("SESSION_COOKIE_SAMESITE", "")
    assert samesite in ("Lax", "Strict"), (
        f"SESSION_COOKIE_SAMESITE is '{samesite}'; expected 'Lax' or 'Strict' (SEC-002)"
    )


def test_admin_unauthenticated_redirects_to_login(secure_app):
    """
    Input: secure_app fixture
    Output: None
    Details:
        An unauthenticated GET to /admin/ must return 302 to the login page,
        not 200. Verifies that @admin_required is enforced.
    """
    with secure_app.test_client() as client:
        resp = client.get("/admin/")
        assert resp.status_code == 302
        location = resp.headers.get("Location", "")
        assert "login" in location.lower(), (
            f"Admin redirect target '{location}' should point to login page"
        )


def test_admin_unauthenticated_does_not_return_200(secure_app):
    """
    Input: secure_app fixture
    Output: None
    Details:
        Complementary to the redirect test: confirms the status code is
        explicitly not 200 for unauthenticated /admin/ access.
    """
    with secure_app.test_client() as client:
        resp = client.get("/admin/")
        assert resp.status_code != 200, (
            "Unauthenticated request to /admin/ returned 200 — access control bypassed"
        )


def test_jinja2_autoescape_enabled(secure_app):
    """
    Input: secure_app fixture
    Output: None
    Details:
        Confirms Jinja2 auto-escape is active for HTML templates. Without this,
        template variables render raw HTML, enabling XSS.
    """
    assert secure_app.jinja_env.autoescape, (
        "Jinja2 auto-escape is disabled — all template variables render raw HTML"
    )


def test_settings_password_requires_login(secure_app):
    """
    Input: secure_app fixture
    Output: None
    Details:
        POST to /settings/password without an active session must redirect
        to login (not return 200 or 400 with a password change applied).
        Validates that unauthenticated POST to a data-modifying route is rejected.
    """
    with secure_app.test_client() as client:
        resp = client.post("/settings/password", data={
            "current_password": "anything",
            "new_password": "newpassword123",
            "confirm_password": "newpassword123",
        })
        # Must redirect to login, not succeed
        assert resp.status_code == 302
        location = resp.headers.get("Location", "")
        assert "login" in location.lower(), (
            f"Unauthenticated POST to /settings/password redirected to '{location}', not login"
        )


def test_history_clear_requires_login(secure_app):
    """
    Input: secure_app fixture
    Output: None
    Details:
        POST to /history/clear without a session must redirect to login.
    """
    with secure_app.test_client() as client:
        resp = client.post("/history/clear")
        assert resp.status_code == 302
        location = resp.headers.get("Location", "")
        assert "login" in location.lower()


def test_admin_post_routes_reject_unauthenticated(secure_app):
    """
    Input: secure_app fixture
    Output: None
    Details:
        POST requests to admin data-modifying routes (crawl-all, vectorize,
        reindex-all) must redirect unauthenticated users to login, not execute.
        Validates @admin_required on write operations.
    """
    with secure_app.test_client() as client:
        admin_post_routes = [
            "/admin/crawl-all",
            "/admin/reindex-all",
            "/admin/vectorize",
        ]
        for route in admin_post_routes:
            resp = client.post(route)
            assert resp.status_code in (302, 401, 403), (
                f"Unauthenticated POST to {route} returned {resp.status_code}, "
                "expected redirect or rejection"
            )
            if resp.status_code == 302:
                location = resp.headers.get("Location", "")
                assert "login" in location.lower(), (
                    f"Unauthenticated POST to {route} redirected to '{location}', not login"
                )


def test_admin_target_delete_requires_admin_role(secure_app):
    """
    Input: secure_app fixture
    Output: None
    Details:
        A logged-in non-admin user POSTing to /admin/targets/<id>/delete
        must receive 403, not 200. Validates role enforcement in admin_required.
    """
    from flask_login import login_user, logout_user

    with secure_app.app_context():
        regular_user = User(username="regular", role="user")
        regular_user.set_password("userpassword123")
        db.session.add(regular_user)
        db.session.commit()
        uid = regular_user.id

    with secure_app.test_client() as client:
        # Log in as regular user
        client.post("/login", data={"username": "regular", "password": "userpassword123"})
        resp = client.post("/admin/targets/1/delete")
        assert resp.status_code == 403, (
            f"Non-admin user received {resp.status_code} on admin DELETE — expected 403"
        )


if __name__ == "__main__":
    pass


def test_create_app_refuses_weak_secret_key(monkeypatch):
    """
    Input:  Config.SECRET_KEY monkeypatched to each weak/placeholder value
    Output: create_app() raises RuntimeError before any DB work
    Details:
        30f #5 — a known signing key allows session-cookie forgery (privilege
        escalation). create_app must fail fast rather than boot with a forgeable
        key. The guard runs immediately after config load, before db.init_app or
        the admin seed, so no DB is touched. app.testing is False here because
        Config does not set TESTING.
    """
    import flask_app
    from flask_app.config import Config

    for weak in ("", "change-me", "change-me-to-a-long-random-string"):
        monkeypatch.setattr(Config, "SECRET_KEY", weak)
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            flask_app.create_app()


def test_create_app_allows_weak_secret_key_in_testing(monkeypatch):
    """
    Input:  Config with a weak SECRET_KEY but TESTING enabled
    Output: the SECRET_KEY guard does not fire (no RuntimeError from the guard)
    Details:
        30f #5 — the fail-fast guard is gated on `not app.testing` so the test
        suite (and any explicit testing context) is never blocked by it. We only
        assert the guard itself does not raise; later DB-dependent steps are out
        of scope and patched away.
    """
    import flask_app
    from flask_app.config import Config

    monkeypatch.setattr(Config, "TESTING", True, raising=False)
    monkeypatch.setattr(Config, "SECRET_KEY", "change-me")
    # Stop create_app right after the guard so it never reaches DB init.
    sentinel = RuntimeError("reached db.init_app")

    def _boom(*_a, **_k):
        raise sentinel

    monkeypatch.setattr(flask_app.db, "init_app", _boom)
    with pytest.raises(RuntimeError) as exc:
        flask_app.create_app()
    # The guard was skipped; the only RuntimeError is our sentinel past the guard.
    assert exc.value is sentinel


def test_create_app_refuses_passwordless_redis_on_network_host(monkeypatch):
    """
    Input:  Config with a blank REDIS_PASSWORD and a non-loopback REDIS_HOST
    Output: create_app() raises RuntimeError before any DB work
    Details:
        30f #9 — Redis is the Celery broker; an unauthenticated, network-reachable
        instance allows task injection (worker code execution). create_app refuses
        to boot in that configuration. A valid SECRET_KEY is set so the earlier
        SECRET_KEY guard does not mask this one.
    """
    import flask_app
    from flask_app.config import Config

    monkeypatch.setattr(Config, "SECRET_KEY", "a-strong-test-secret-value")
    monkeypatch.setattr(Config, "REDIS_HOST", "172.27.72.57")
    monkeypatch.setattr(Config, "REDIS_PASSWORD", "")
    with pytest.raises(RuntimeError, match="REDIS_PASSWORD"):
        flask_app.create_app()


def test_create_app_allows_passwordless_redis_on_loopback(monkeypatch):
    """
    Input:  blank REDIS_PASSWORD but a loopback REDIS_HOST (development)
    Output: the Redis guard does not fire
    Details:
        30f #9 — a passwordless Redis on localhost is a dev convenience and is
        permitted. We stop create_app right after the guards (sentinel on
        db.init_app) so the test never needs a live DB.
    """
    import flask_app
    from flask_app.config import Config

    monkeypatch.setattr(Config, "SECRET_KEY", "a-strong-test-secret-value")
    monkeypatch.setattr(Config, "REDIS_HOST", "localhost")
    monkeypatch.setattr(Config, "REDIS_PASSWORD", "")
    sentinel = RuntimeError("reached db.init_app")

    def _boom(*_a, **_k):
        raise sentinel

    monkeypatch.setattr(flask_app.db, "init_app", _boom)
    with pytest.raises(RuntimeError) as exc:
        flask_app.create_app()
    assert exc.value is sentinel


def test_proxyfix_trusts_one_forwarded_hop(monkeypatch):
    """
    Input:  an app built by create_app(); a request carrying X-Forwarded-For
    Output: request.remote_addr reflects the forwarded client IP, not the peer
    Details:
        30f #7 — behind Nginx, ProxyFix(x_for=1) must surface the real client IP
        so the IP-keyed login rate limit and audit logs are meaningful. Strong
        SECRET_KEY and loopback Redis are set so the startup guards pass.
    """
    from werkzeug.middleware.proxy_fix import ProxyFix
    import flask_app
    from flask_app.config import Config

    monkeypatch.setattr(Config, "SECRET_KEY", "strong-secret-value-for-proxyfix")
    monkeypatch.setattr(Config, "REDIS_HOST", "localhost")
    monkeypatch.setattr(Config, "REDIS_PASSWORD", "")
    app = flask_app.create_app()
    assert isinstance(app.wsgi_app, ProxyFix)

    @app.route("/_t_remote_addr")
    def _t_remote_addr():
        from flask import request
        return request.remote_addr or ""

    client = app.test_client()
    r = client.get("/_t_remote_addr", headers={"X-Forwarded-For": "203.0.113.7"})
    assert r.data.decode() == "203.0.113.7"


def test_create_app_logging_handler_is_idempotent(monkeypatch):
    """
    Input:  create_app() called twice in the same process
    Output: the root logger gains no additional flask.log handler on the 2nd call
    Details:
        30f #12 — create_app must not stack a new RotatingFileHandler each call;
        otherwise a worker that rebuilds its app writes every log line N times.
    """
    import logging
    from logging.handlers import RotatingFileHandler
    import flask_app
    from flask_app.config import Config

    monkeypatch.setattr(Config, "SECRET_KEY", "a-strong-test-secret-value")
    monkeypatch.setattr(Config, "REDIS_HOST", "localhost")
    monkeypatch.setattr(Config, "REDIS_PASSWORD", "")

    def _flask_log_handlers():
        return [h for h in logging.root.handlers
                if isinstance(h, RotatingFileHandler)
                and getattr(h, "baseFilename", "").endswith("flask.log")]

    flask_app.create_app()
    count_after_first = len(_flask_log_handlers())
    flask_app.create_app()
    count_after_second = len(_flask_log_handlers())

    assert count_after_first >= 1
    assert count_after_second == count_after_first
