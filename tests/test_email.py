"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for Epic 19b (Email Password Recovery): SMTP email helper,
    forgot-password and reset-password routes, login page link,
    enumeration protection.
"""
# Imports
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import pytest
from flask import Flask
from flask_app import db, login_manager, oauth
from flask_app.models.user import User
from flask_app.models.password_reset_token import PasswordResetToken

# Globals
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "templates")
_STATIC_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "static")


# Functions
@pytest.fixture
def email_app():
    """
    Input: None
    Output: Flask test app with SMTP configured and all auth routes registered
    Details:
        Uses SQLite in-memory. SMTP_HOST set so the forgot-password flow is active.
    """
    from flask_app.models.search_history import SearchHistory  # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget  # noqa: F401
    from flask_app.models.crawl_job import CrawlJob            # noqa: F401
    from flask_app.routes.auth import auth_bp
    from flask_app.routes.search import search_bp
    from flask_app.routes.admin import admin_bp

    test_app = Flask("test_email", template_folder=_TEMPLATE_DIR, static_folder=_STATIC_DIR)
    test_app.config["TESTING"] = True
    test_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    test_app.config["SECRET_KEY"] = "test-email-secret"
    test_app.config["SMTP_HOST"] = "smtp.test.local"
    test_app.config["SMTP_PORT"] = 587
    test_app.config["SMTP_USER"] = ""
    test_app.config["SMTP_PASSWORD"] = ""
    test_app.config["SMTP_FROM"] = "noreply@test.local"
    test_app.config["SMTP_TLS"] = True
    test_app.config["APP_URL"] = "http://localhost:5000"

    db.init_app(test_app)
    login_manager.init_app(test_app)

    test_app.register_blueprint(auth_bp)
    test_app.register_blueprint(search_bp)
    test_app.register_blueprint(admin_bp, url_prefix="/admin")

    with test_app.app_context():
        db.create_all()
        yield test_app
        db.drop_all()


@pytest.fixture
def no_smtp_app():
    """
    Input: None
    Output: Flask test app with SMTP_HOST blank (email disabled)
    """
    from flask_app.models.search_history import SearchHistory  # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget  # noqa: F401
    from flask_app.models.crawl_job import CrawlJob            # noqa: F401
    from flask_app.routes.auth import auth_bp
    from flask_app.routes.search import search_bp
    from flask_app.routes.admin import admin_bp

    test_app = Flask("test_no_smtp", template_folder=_TEMPLATE_DIR, static_folder=_STATIC_DIR)
    test_app.config["TESTING"] = True
    test_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    test_app.config["SECRET_KEY"] = "test-no-smtp-secret"
    test_app.config["SMTP_HOST"] = ""

    db.init_app(test_app)
    login_manager.init_app(test_app)

    test_app.register_blueprint(auth_bp)
    test_app.register_blueprint(search_bp)
    test_app.register_blueprint(admin_bp, url_prefix="/admin")

    with test_app.app_context():
        db.create_all()
        yield test_app
        db.drop_all()


def test_send_email_no_smtp_host():
    """
    Input: None
    Output: None
    Details:
        send_email returns False without attempting SMTP when SMTP_HOST is blank.
    """
    from flask_app.services.email import send_email
    from flask_app import config as cfg_module
    original = cfg_module.Config.SMTP_HOST
    try:
        cfg_module.Config.SMTP_HOST = ""
        result = send_email("user@example.com", "Subject", "Body")
        assert result is False
    finally:
        cfg_module.Config.SMTP_HOST = original


def test_send_email_success():
    """
    Input: None
    Output: None
    Details:
        send_email returns True when SMTP connection succeeds (mocked SMTP).
    """
    from flask_app.services.email import send_email
    from flask_app import config as cfg_module
    original = cfg_module.Config.SMTP_HOST
    try:
        cfg_module.Config.SMTP_HOST = "smtp.test.local"
        with patch("flask_app.services.email.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = send_email("dest@example.com", "Hello", "World")
        assert result is True
    finally:
        cfg_module.Config.SMTP_HOST = original


def test_forgot_password_sends_email_for_known_user(email_app):
    """
    Input: email_app fixture
    Output: None
    Details:
        POST /forgot-password with a known username triggers send_email.
        Response is always 200 (no enumeration leak).
    """
    with email_app.app_context():
        user = User(username="recoverme", role="user")
        user.set_password("old_pass")
        db.session.add(user)
        db.session.commit()

    client = email_app.test_client()
    with patch("flask_app.services.email.send_email", return_value=True) as mock_send:
        response = client.post("/forgot-password", data={"username": "recoverme"})
    assert response.status_code == 200
    mock_send.assert_called_once()

    with email_app.app_context():
        token = db.session.execute(
            db.select(PasswordResetToken).filter_by(user_id=1)
        ).scalar_one_or_none()
        assert token is not None
        assert not token.used
        assert token.is_valid()


def test_forgot_password_no_email_for_unknown_user(email_app):
    """
    Input: email_app fixture
    Output: None
    Details:
        POST /forgot-password with an unknown username returns 200 without
        calling send_email (enumeration protection).
    """
    client = email_app.test_client()
    with patch("flask_app.services.email.send_email", return_value=True) as mock_send:
        response = client.post("/forgot-password", data={"username": "doesnotexist"})
    assert response.status_code == 200
    mock_send.assert_not_called()


def test_reset_password_valid_token(email_app):
    """
    Input: email_app fixture
    Output: None
    Details:
        GET /reset-password/<valid_token> renders the form (200).
        POST with matching passwords resets the password, marks token used,
        and redirects to login.
    """
    with email_app.app_context():
        user = User(username="resetuser", role="user")
        user.set_password("old_pass")
        db.session.add(user)
        db.session.flush()
        token_obj = PasswordResetToken.create_for_user(user.id)
        db.session.add(token_obj)
        db.session.commit()
        token_str = token_obj.token

    client = email_app.test_client()
    response = client.get(f"/reset-password/{token_str}")
    assert response.status_code == 200

    response = client.post(f"/reset-password/{token_str}", data={
        "new_password": "newpass123",
        "confirm_password": "newpass123",
    })
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    with email_app.app_context():
        user = db.session.execute(
            db.select(User).filter_by(username="resetuser")
        ).scalar_one()
        assert user.check_password("newpass123")
        token = db.session.execute(
            db.select(PasswordResetToken).filter_by(token=token_str)
        ).scalar_one()
        assert token.used


def test_reset_password_expired_token(email_app):
    """
    Input: email_app fixture
    Output: None
    Details:
        GET /reset-password/<expired_token> returns 400.
    """
    with email_app.app_context():
        user = User(username="expireduser", role="user")
        user.set_password("old_pass")
        db.session.add(user)
        db.session.flush()
        token_obj = PasswordResetToken(
            user_id=user.id,
            expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
        )
        db.session.add(token_obj)
        db.session.commit()
        token_str = token_obj.token

    client = email_app.test_client()
    response = client.get(f"/reset-password/{token_str}")
    assert response.status_code == 400


def test_reset_password_used_token(email_app):
    """
    Input: email_app fixture
    Output: None
    Details:
        A token that is already marked used returns 400.
    """
    with email_app.app_context():
        user = User(username="usedtokenuser", role="user")
        user.set_password("old_pass")
        db.session.add(user)
        db.session.flush()
        token_obj = PasswordResetToken.create_for_user(user.id)
        token_obj.used = True
        db.session.add(token_obj)
        db.session.commit()
        token_str = token_obj.token

    client = email_app.test_client()
    response = client.get(f"/reset-password/{token_str}")
    assert response.status_code == 400


def test_forgot_password_link_absent_without_smtp(no_smtp_app):
    """
    Input: no_smtp_app fixture
    Output: None
    Details:
        The login page must not render the "Forgot password?" link when
        SMTP is not configured.
    """
    client = no_smtp_app.test_client()
    response = client.get("/login")
    assert response.status_code == 200
    assert b"Forgot password" not in response.data


def test_forgot_password_link_present_with_smtp(email_app):
    """
    Input: email_app fixture
    Output: None
    Details:
        The login page renders the "Forgot password?" link when SMTP is configured.
    """
    client = email_app.test_client()
    response = client.get("/login")
    assert response.status_code == 200
    assert b"Forgot password" in response.data


if __name__ == "__main__":
    pass
