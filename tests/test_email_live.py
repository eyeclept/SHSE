"""
Author: Richard Baldwin
Date:   2026
Email:  eyeclept@pm.me

Description:
    Integration tests for Epic 19b (Email Password Recovery) against Mailpit.
    Mailpit is a local catch-all SMTP server — no email leaves the homelab network.
    All tests skip automatically when Mailpit is unreachable so the main suite
    passes in environments without the services VM.

    Default target: 172.27.72.57 (override with MAILPIT_HOST / MAILPIT_SMTP_PORT /
    MAILPIT_API_PORT env vars).

    Run live tests explicitly:
        MAILPIT_HOST=172.27.72.57 pytest tests/test_email_live.py -v
"""
# Imports
import logging
import os
import time
from unittest.mock import patch

import pytest
import requests
from flask import Flask

# Globals
logger = logging.getLogger(__name__)

MAILPIT_HOST      = os.environ.get("MAILPIT_HOST",      "172.27.72.57")
MAILPIT_SMTP_PORT = int(os.environ.get("MAILPIT_SMTP_PORT", "1025"))
MAILPIT_API_PORT  = int(os.environ.get("MAILPIT_API_PORT",  "8025"))
_MAILPIT_API      = f"http://{MAILPIT_HOST}:{MAILPIT_API_PORT}"

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "templates")
_STATIC_DIR   = os.path.join(_PROJECT_ROOT, "flask_app", "static")


def _mailpit_up() -> bool:
    """
    Input: None
    Output: True if Mailpit's API is reachable; False otherwise
    Details:
        Called once at module load — sets the skip condition for all @mailpit tests.
        1-second timeout keeps pytest collection fast when the VM is offline.
    """
    try:
        r = requests.get(f"{_MAILPIT_API}/api/v1/info", timeout=1)
        return r.status_code == 200
    except Exception:
        logger.warning("Mailpit not reachable at %s — live email tests will skip", _MAILPIT_API)
        return False


_mailpit_reachable = _mailpit_up()

mailpit = pytest.mark.skipif(
    not _mailpit_reachable,
    reason=f"Mailpit not reachable at {MAILPIT_HOST}:{MAILPIT_API_PORT} — start services VM first",
)


def _clear_mailpit() -> None:
    """
    Input: None
    Output: None
    Details: Deletes all messages from Mailpit; called at the start of each test.
    """
    requests.delete(f"{_MAILPIT_API}/api/v1/messages", timeout=5)


def _list_messages() -> list:
    """
    Input: None
    Output: list of Mailpit message summaries
    """
    r = requests.get(f"{_MAILPIT_API}/api/v1/messages", timeout=5)
    return r.json().get("messages", []) or []


def _get_message_body(msg_id: str) -> str:
    """
    Input: Mailpit message ID
    Output: plain-text body of the message
    """
    r = requests.get(f"{_MAILPIT_API}/api/v1/message/{msg_id}", timeout=5)
    return r.json().get("Text", "")


# Functions
@pytest.fixture
def smtp_app():
    """
    Input: None
    Output: Flask test app with SQLite and auth routes, no external dependencies
    Details:
        SMTP host is NOT set in the app config here — each live test patches
        Config directly so the send_email() helper hits Mailpit.
    """
    from flask_app import db, login_manager, oauth  # noqa: F401
    from flask_app.models.search_history import SearchHistory        # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget        # noqa: F401
    from flask_app.models.crawl_job import CrawlJob                  # noqa: F401
    from flask_app.models.password_reset_token import PasswordResetToken  # noqa: F401
    from flask_app.routes.auth import auth_bp
    from flask_app.routes.search import search_bp
    from flask_app.routes.admin import admin_bp

    app = Flask("test_email_live", template_folder=_TEMPLATE_DIR, static_folder=_STATIC_DIR)
    app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SECRET_KEY": "live-email-test-secret",
        "APP_URL": "http://localhost:5000",
    })

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    app.register_blueprint(auth_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@mailpit
def test_send_email_delivers_to_mailpit():
    """
    Input: None
    Output: None
    Details:
        Calls send_email() with Config patched to point at Mailpit.
        Verifies via Mailpit REST API that exactly one message arrived with the
        expected recipient and subject.
    """
    _clear_mailpit()
    from flask_app.services.email import send_email
    from flask_app import config as cfg_module

    with (
        patch.object(cfg_module.Config, "SMTP_HOST", MAILPIT_HOST),
        patch.object(cfg_module.Config, "SMTP_PORT", MAILPIT_SMTP_PORT),
        patch.object(cfg_module.Config, "SMTP_TLS",  False),
        patch.object(cfg_module.Config, "SMTP_USER", ""),
        patch.object(cfg_module.Config, "SMTP_FROM", "noreply@shse.local"),
    ):
        result = send_email("recipient@shse.local", "SHSE delivery test", "Integration test body")

    assert result is True, "send_email returned False — Mailpit SMTP port may be down"
    msgs = _list_messages()
    assert len(msgs) == 1, f"Expected 1 message in Mailpit, got {len(msgs)}"
    assert msgs[0]["To"][0]["Address"] == "recipient@shse.local"
    assert msgs[0]["Subject"] == "SHSE delivery test"


@mailpit
def test_forgot_password_email_arrives_in_mailpit(smtp_app):
    """
    Input: smtp_app fixture
    Output: None
    Details:
        POST /forgot-password for a known user; verifies Mailpit receives the email
        and a PasswordResetToken row exists in the DB.
    """
    _clear_mailpit()
    from flask_app import db
    from flask_app.models.user import User
    from flask_app.models.password_reset_token import PasswordResetToken
    from flask_app import config as cfg_module

    # Username must be an email address: the route sends to=username via SMTP
    test_username = "live_reset_user@shse.local"

    with smtp_app.app_context():
        user = User(username=test_username, role="user")
        user.set_password("livepass1!")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    client = smtp_app.test_client()
    with (
        patch.object(cfg_module.Config, "SMTP_HOST", MAILPIT_HOST),
        patch.object(cfg_module.Config, "SMTP_PORT", MAILPIT_SMTP_PORT),
        patch.object(cfg_module.Config, "SMTP_TLS",  False),
        patch.object(cfg_module.Config, "SMTP_USER", ""),
        patch.object(cfg_module.Config, "SMTP_FROM", "noreply@shse.local"),
    ):
        resp = client.post("/forgot-password", data={"username": test_username})

    assert resp.status_code == 200
    time.sleep(0.5)
    msgs = _list_messages()
    assert msgs, "No email arrived in Mailpit after /forgot-password submission"
    subjects = [m["Subject"] for m in msgs]
    assert any("password" in s.lower() or "reset" in s.lower() for s in subjects), (
        f"Expected a password-reset subject, got: {subjects}"
    )

    with smtp_app.app_context():
        token = db.session.execute(
            db.select(PasswordResetToken).filter_by(user_id=user_id)
        ).scalar_one_or_none()
        assert token is not None, "No PasswordResetToken row created in DB"
        assert token.is_valid(), "Token should be valid (not expired, not used)"


@mailpit
def test_reset_link_in_email_body(smtp_app):
    """
    Input: smtp_app fixture
    Output: None
    Details:
        Verifies the email body contains a /reset-password/<token> URL that the
        user can click to complete the reset flow.
    """
    _clear_mailpit()
    from flask_app import db
    from flask_app.models.user import User
    from flask_app import config as cfg_module

    test_username = "link_check_user@shse.local"

    with smtp_app.app_context():
        user = User(username=test_username, role="user")
        user.set_password("linkpass1!")
        db.session.add(user)
        db.session.commit()

    client = smtp_app.test_client()
    with (
        patch.object(cfg_module.Config, "SMTP_HOST", MAILPIT_HOST),
        patch.object(cfg_module.Config, "SMTP_PORT", MAILPIT_SMTP_PORT),
        patch.object(cfg_module.Config, "SMTP_TLS",  False),
        patch.object(cfg_module.Config, "SMTP_USER", ""),
        patch.object(cfg_module.Config, "SMTP_FROM", "noreply@shse.local"),
    ):
        client.post("/forgot-password", data={"username": test_username})

    time.sleep(0.5)
    msgs = _list_messages()
    assert msgs, "No email in Mailpit"
    body = _get_message_body(msgs[0]["ID"])
    assert "/reset-password/" in body, (
        f"Expected /reset-password/<token> link in email body, got: {body!r}"
    )


@mailpit
def test_unknown_user_sends_no_email(smtp_app):
    """
    Input: smtp_app fixture
    Output: None
    Details:
        POST /forgot-password with an unknown username returns 200 (same as known
        user — enumeration protection) but delivers no email to Mailpit.
    """
    _clear_mailpit()
    client = smtp_app.test_client()
    from flask_app import config as cfg_module

    with (
        patch.object(cfg_module.Config, "SMTP_HOST", MAILPIT_HOST),
        patch.object(cfg_module.Config, "SMTP_PORT", MAILPIT_SMTP_PORT),
        patch.object(cfg_module.Config, "SMTP_TLS",  False),
        patch.object(cfg_module.Config, "SMTP_USER", ""),
        patch.object(cfg_module.Config, "SMTP_FROM", "noreply@shse.local"),
    ):
        resp = client.post("/forgot-password", data={"username": "nobody_here"})

    assert resp.status_code == 200
    time.sleep(0.2)
    msgs = _list_messages()
    assert len(msgs) == 0, (
        f"Expected no email for unknown user, got {len(msgs)} message(s) in Mailpit"
    )


if __name__ == "__main__":
    pass
