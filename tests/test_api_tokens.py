"""
Author: Richard Baldwin
Date:   2026
Email:  eyeclept@pm.me

Description:
    Tests for the API token authentication system.
    Covers LocalBackend HMAC/verify, ApiToken model (generate/verify/expiry/revoke),
    api_v1 blueprint access-control, and the api.enabled kill-switch.
    Uses in-memory SQLite with all models imported before db.create_all().
"""
# Imports
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask_app import db, login_manager

# Globals
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "templates")
_STATIC_DIR   = os.path.join(_PROJECT_ROOT, "flask_app", "static")


# Functions
@pytest.fixture
def app():
    """
    Input: None
    Output: Flask test app with all models, blueprints, and in-memory SQLite
    Details:
        Mirrors the pattern from test_admin.py.  All models must be imported
        before db.create_all() so SQLAlchemy can resolve relationship strings.
    """
    from flask_app.models.user import User                                    # noqa: F401
    from flask_app.models.search_history import SearchHistory                 # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget                 # noqa: F401
    from flask_app.models.crawl_job import CrawlJob                           # noqa: F401
    from flask_app.models.system_setting import SystemSetting                 # noqa: F401
    from flask_app.models.api_token import ApiToken                           # noqa: F401
    from flask_app.models.password_reset_token import PasswordResetToken      # noqa: F401
    from flask_app.models.webauthn_credential import WebAuthnCredential       # noqa: F401
    from flask_app.routes.auth import auth_bp
    from flask_app.routes.search import search_bp
    from flask_app.routes.admin import admin_bp
    from flask_app.routes.api import api_bp
    from flask_wtf.csrf import CSRFProtect

    flask_app = Flask(
        "test_api_tokens",
        template_folder=_TEMPLATE_DIR,
        static_folder=_STATIC_DIR,
    )
    flask_app.config.update({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "WTF_CSRF_ENABLED": False,
        "SSO_ENABLED": False,
        "PROPAGATE_EXCEPTIONS": False,
    })
    csrf = CSRFProtect()

    db.init_app(flask_app)
    login_manager.init_app(flask_app)
    login_manager.login_view = "auth.login"
    csrf.init_app(flask_app)

    flask_app.register_blueprint(auth_bp)
    flask_app.register_blueprint(search_bp)
    flask_app.register_blueprint(admin_bp, url_prefix="/admin")
    flask_app.register_blueprint(api_bp)
    csrf.exempt(api_bp)

    with flask_app.app_context():
        db.create_all()
        yield flask_app


@pytest.fixture
def client(app):
    """
    Input: app fixture
    Output: Flask test client
    """
    return app.test_client()


@pytest.fixture
def admin_user(app):
    """
    Input: app fixture
    Output: User ORM instance with role='admin' committed to the test DB
    """
    from flask_app.models.user import User
    with app.app_context():
        u = User(username="tokenadmin", role="admin")
        u.set_password("adminpass123")
        db.session.add(u)
        db.session.commit()
        # Re-fetch to get a usable, attached instance
        return db.session.get(User, u.id)


@pytest.fixture
def regular_user(app):
    """
    Input: app fixture
    Output: User ORM instance with role='user' committed to the test DB
    """
    from flask_app.models.user import User
    with app.app_context():
        u = User(username="tokenuser", role="user")
        u.set_password("userpass123")
        db.session.add(u)
        db.session.commit()
        return db.session.get(User, u.id)


@pytest.fixture
def admin_token(app, admin_user):
    """
    Input: app, admin_user fixtures
    Output: (ApiToken ORM instance, raw_token str) for the admin user
    """
    from flask_app.models.api_token import ApiToken
    with app.app_context():
        user = db.session.get(type(admin_user), admin_user.id)
        token, raw = ApiToken.generate(name="ci-admin", user=user)
        db.session.add(token)
        db.session.commit()
        token_id = token.id
        return db.session.get(ApiToken, token_id), raw


@pytest.fixture
def user_token(app, regular_user):
    """
    Input: app, regular_user fixtures
    Output: (ApiToken ORM instance, raw_token str) for the regular user
    """
    from flask_app.models.api_token import ApiToken
    with app.app_context():
        user = db.session.get(type(regular_user), regular_user.id)
        token, raw = ApiToken.generate(name="ci-user", user=user)
        db.session.add(token)
        db.session.commit()
        token_id = token.id
        return db.session.get(ApiToken, token_id), raw


# ── LocalBackend tests ───────────────────────────────────────────────────────

def test_local_backend_hmac_is_consistent(app):
    """
    Input: same raw_token called twice
    Output: identical hex digests
    Details:
        Deterministic HMAC must return the same hash for the same input.
    """
    from flask_app.services.token_backend import LocalBackend
    with app.app_context():
        backend = LocalBackend()
        h1 = backend.hmac("shse_testtoken123")
        h2 = backend.hmac("shse_testtoken123")
        assert h1 == h2
        assert len(h1) == 64        # SHA-256 hex digest is always 64 chars
        assert h1.isalnum()         # hex chars only


def test_local_backend_verify_accepts_correct_token(app):
    """
    Input: raw token and its stored HMAC
    Output: verify() returns True
    """
    from flask_app.services.token_backend import LocalBackend
    with app.app_context():
        backend = LocalBackend()
        raw = "shse_correct_token"
        stored = backend.hmac(raw)
        assert backend.verify(raw, stored) is True


def test_local_backend_verify_rejects_wrong_token(app):
    """
    Input: wrong raw token compared against a stored HMAC
    Output: verify() returns False (timing-safe compare_digest used)
    """
    from flask_app.services.token_backend import LocalBackend
    with app.app_context():
        backend = LocalBackend()
        stored = backend.hmac("shse_correct_token")
        assert backend.verify("shse_wrong_token", stored) is False


# ── ApiToken model tests ─────────────────────────────────────────────────────

def test_generate_returns_shse_prefixed_raw_token(app, admin_user):
    """
    Input: admin User instance
    Output: raw token starts with 'shse_'; stored hash differs from raw token
    """
    from flask_app.models.api_token import ApiToken
    with app.app_context():
        user = db.session.get(type(admin_user), admin_user.id)
        token, raw = ApiToken.generate(name="test", user=user)
        assert raw.startswith("shse_")
        assert token.token_hash != raw
        assert len(token.token_hash) == 64


def test_verify_returns_token_for_correct_raw(app, admin_token):
    """
    Input: correct raw token string
    Output: ApiToken.verify() returns the matching ApiToken instance
    """
    from flask_app.models.api_token import ApiToken
    token_obj, raw = admin_token
    with app.app_context():
        found = ApiToken.verify(raw)
        assert found is not None
        assert found.id == token_obj.id


def test_verify_returns_none_for_wrong_token(app, admin_token):
    """
    Input: wrong raw token string
    Output: ApiToken.verify() returns None
    """
    from flask_app.models.api_token import ApiToken
    with app.app_context():
        found = ApiToken.verify("shse_definitely_wrong_token_xxx")
        assert found is None


def test_verify_returns_none_for_revoked_token(app, admin_token):
    """
    Input: raw token for a revoked ApiToken
    Output: ApiToken.verify() returns None
    """
    from flask_app.models.api_token import ApiToken
    token_obj, raw = admin_token
    with app.app_context():
        t = db.session.get(ApiToken, token_obj.id)
        t.revoked_at = datetime.utcnow()
        db.session.commit()
        found = ApiToken.verify(raw)
        assert found is None


def test_verify_returns_none_for_expired_token(app, admin_user):
    """
    Input: raw token for an expired ApiToken (expires_at in the past)
    Output: ApiToken.verify() returns None
    """
    from flask_app.models.api_token import ApiToken
    with app.app_context():
        user = db.session.get(type(admin_user), admin_user.id)
        token, raw = ApiToken.generate(name="expired", user=user)
        token.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.add(token)
        db.session.commit()
        found = ApiToken.verify(raw)
        assert found is None


# ── /api/v1 access-control tests ────────────────────────────────────────────

def test_targets_returns_401_with_no_auth(client, app):
    """
    Input: GET /api/v1/targets with no Authorization header
    Output: 401 JSON {"error": "authentication required"}
    """
    with app.app_context():
        r = client.get("/api/v1/targets")
        assert r.status_code == 401
        data = r.get_json()
        assert data is not None
        assert "error" in data


def test_targets_returns_200_with_valid_admin_token(client, app, admin_token):
    """
    Input: GET /api/v1/targets with valid Bearer token for an admin user
    Output: 200 JSON array
    """
    _, raw = admin_token
    with app.app_context():
        r = client.get(
            "/api/v1/targets",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)


def test_targets_returns_403_with_user_role_token(client, app, user_token):
    """
    Input: GET /api/v1/targets with valid Bearer token for a non-admin user
    Output: 403 JSON {"error": "admin role required"}
    """
    _, raw = user_token
    with app.app_context():
        r = client.get(
            "/api/v1/targets",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 403
        data = r.get_json()
        assert "error" in data


def test_post_targets_creates_target_and_returns_201(client, app, admin_token):
    """
    Input: POST /api/v1/targets with valid admin token and JSON body
    Output: 201 JSON {"ok": true, "id": <int>}
    """
    _, raw = admin_token
    with app.app_context():
        payload = {
            "target_type": "service",
            "nickname": "api-test-target",
            "url": "http://example.com",
            "crawl_depth": 2,
        }
        r = client.post(
            "/api/v1/targets",
            json=payload,
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 201
        data = r.get_json()
        assert data.get("ok") is True
        assert isinstance(data.get("id"), int)


def test_post_targets_crawl_returns_202_and_dispatches(client, app, admin_token):
    """
    Input: POST /api/v1/targets/<id>/crawl with valid admin token
    Output: 202 JSON {"ok": true}; celery task dispatched (mocked)
    """
    from flask_app.models.crawler_target import CrawlerTarget
    _, raw = admin_token
    with app.app_context():
        # Create a target to crawl
        t = CrawlerTarget(target_type="service", nickname="crawl-test", url="http://ex.com")
        db.session.add(t)
        db.session.commit()
        target_id = t.id

    mock_result = MagicMock()
    mock_result.id = "fake-task-id-999"

    with patch("flask_app.routes.api.login_user"), \
         patch("celery_worker.tasks.crawl.crawl_target") as mock_task:
        mock_task.delay.return_value = mock_result
        with app.app_context():
            r = client.post(
                f"/api/v1/targets/{target_id}/crawl",
                headers={"Authorization": f"Bearer {raw}"},
            )
        assert r.status_code == 202
        data = r.get_json()
        assert data.get("ok") is True


def test_api_disabled_returns_503(client, app, admin_token):
    """
    Input: valid admin token; api.enabled = '0' in SystemSetting
    Output: 503 response even with a valid token
    """
    from flask_app.models.system_setting import SystemSetting
    _, raw = admin_token
    with app.app_context():
        row = SystemSetting(key="api.enabled", value="0")
        db.session.add(row)
        db.session.commit()

    try:
        r = client.get(
            "/api/v1/targets",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 503
    finally:
        # Clean up so other tests are not affected
        with app.app_context():
            row = db.session.get(SystemSetting, "api.enabled")
            if row:
                db.session.delete(row)
                db.session.commit()


def test_revoked_token_returns_401(client, app, admin_token):
    """
    Input: raw token for a revoked ApiToken
    Output: 401 JSON {"error": "authentication required"}
    """
    from flask_app.models.api_token import ApiToken
    token_obj, raw = admin_token
    with app.app_context():
        t = db.session.get(ApiToken, token_obj.id)
        t.revoked_at = datetime.utcnow()
        db.session.commit()

    r = client.get(
        "/api/v1/targets",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 401
    data = r.get_json()
    assert "error" in data


def test_token_last_used_at_write_is_throttled(app, admin_token):
    """
    Input: repeated Bearer-token auths via load_user_from_request
    Output: last_used_at is written on first use and after the throttle window,
            but NOT on a second auth inside the window
    Details:
        Finding #14 — last_used_at was committed on every authenticated request.
        It should only be persisted when the stored value is stale.
    """
    from datetime import datetime, timedelta
    from flask import request
    from flask_app import load_user_from_request, db, _TOKEN_LAST_USED_THROTTLE
    from flask_app.models.api_token import ApiToken

    token_obj, raw = admin_token
    tid = token_obj.id
    headers = {"Authorization": f"Bearer {raw}"}

    def do_auth():
        with app.test_request_context("/", headers=headers):
            return load_user_from_request(request)

    def last_used():
        with app.app_context():
            return db.session.get(ApiToken, tid).last_used_at

    # First auth: last_used_at was None -> written.
    assert do_auth() is not None
    first = last_used()
    assert first is not None

    # Second auth within the throttle window -> not rewritten.
    do_auth()
    assert last_used() == first

    # Make the stored timestamp stale -> next auth rewrites it.
    with app.app_context():
        t = db.session.get(ApiToken, tid)
        t.last_used_at = datetime.utcnow() - timedelta(seconds=_TOKEN_LAST_USED_THROTTLE + 5)
        db.session.commit()
        stale = t.last_used_at
    do_auth()
    assert last_used() > stale


if __name__ == "__main__":
    pass
