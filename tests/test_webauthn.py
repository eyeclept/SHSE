"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for Epic 19c (2FA): TOTP enrollment, login challenge, disable;
    WebAuthn/FIDO2 registration, authentication, and key management.
    Hardware operations (py_webauthn verify_*) are mocked.
"""
# Imports
import os
import json
import base64
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
import pytest
from flask import Flask
from flask_app import db, login_manager

# Globals
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "templates")
_STATIC_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "static")


# Functions
@pytest.fixture
def twofa_app():
    """
    Input: None
    Output: Flask test app with all 2FA routes registered
    Details:
        Uses SQLite in-memory. Registers auth, search, and admin blueprints.
    """
    from flask_app.models.search_history import SearchHistory  # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget  # noqa: F401
    from flask_app.models.crawl_job import CrawlJob            # noqa: F401
    from flask_app.models.password_reset_token import PasswordResetToken  # noqa: F401
    from flask_app.models.webauthn_credential import WebAuthnCredential   # noqa: F401
    from flask_app.routes.auth import auth_bp
    from flask_app.routes.search import search_bp
    from flask_app.routes.admin import admin_bp

    test_app = Flask("test_2fa", template_folder=_TEMPLATE_DIR, static_folder=_STATIC_DIR)
    test_app.config["TESTING"] = True
    test_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    test_app.config["SECRET_KEY"] = "test-2fa-secret"
    test_app.config["WEBAUTHN_RP_ID"] = "localhost"
    test_app.config["WEBAUTHN_RP_NAME"] = "SHSE Test"
    test_app.config["WEBAUTHN_ORIGIN"] = "http://localhost:5000"

    db.init_app(test_app)
    login_manager.init_app(test_app)

    test_app.register_blueprint(auth_bp)
    test_app.register_blueprint(search_bp)
    test_app.register_blueprint(admin_bp, url_prefix="/admin")

    with test_app.app_context():
        db.create_all()
        yield test_app
        db.drop_all()


def _login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


# ── TOTP tests ────────────────────────────────────────────────────────────────

def test_totp_setup_get_returns_secret_and_uri(twofa_app):
    """
    Input: twofa_app fixture
    Output: None
    Details:
        GET /settings/2fa/setup while authenticated returns JSON with 'secret'
        and 'uri'. The URI must start with 'otpauth://totp/'.
    """
    import pyotp
    from flask_app.models.user import User

    with twofa_app.app_context():
        user = User(username="totpsetupuser", role="user")
        user.set_password("pass")
        db.session.add(user)
        db.session.commit()

    client = twofa_app.test_client()
    _login(client, "totpsetupuser", "pass")
    response = client.get("/settings/2fa/setup")
    assert response.status_code == 200
    data = response.get_json()
    assert "secret" in data
    assert "uri" in data
    assert data["uri"].startswith("otpauth://totp/")
    assert pyotp.TOTP(data["secret"]).verify(pyotp.TOTP(data["secret"]).now())


def test_totp_enrollment_valid_code(twofa_app):
    """
    Input: twofa_app fixture
    Output: None
    Details:
        POST /settings/2fa/setup with a valid TOTP code enables TOTP for the user.
        user.totp_enabled must be True after POST.
    """
    import pyotp
    from flask_app.models.user import User

    with twofa_app.app_context():
        user = User(username="totpenrolluser", role="user")
        user.set_password("pass")
        db.session.add(user)
        db.session.commit()

    client = twofa_app.test_client()
    _login(client, "totpenrolluser", "pass")

    get_resp = client.get("/settings/2fa/setup")
    secret = get_resp.get_json()["secret"]
    code = pyotp.TOTP(secret).now()

    post_resp = client.post("/settings/2fa/setup", data={"code": code})
    assert post_resp.status_code == 302

    with twofa_app.app_context():
        user = db.session.execute(
            db.select(User).filter_by(username="totpenrolluser")
        ).scalar_one()
        assert user.totp_enabled is True
        assert user.totp_secret is not None


def test_totp_login_redirects_to_challenge(twofa_app):
    """
    Input: twofa_app fixture
    Output: None
    Details:
        A user with TOTP enabled must be redirected to /login/2fa after
        correct password entry instead of being logged in directly.
    """
    import pyotp
    from flask_app.models.user import User

    with twofa_app.app_context():
        user = User(username="totp2faloginuser", role="user")
        user.set_password("pass")
        user.totp_secret = pyotp.random_base32()
        user.totp_enabled = True
        db.session.add(user)
        db.session.commit()

    client = twofa_app.test_client()
    response = _login(client, "totp2faloginuser", "pass")
    assert response.status_code == 302
    assert "/login/2fa" in response.headers["Location"]


def test_totp_challenge_correct_code_completes_login(twofa_app):
    """
    Input: twofa_app fixture
    Output: None
    Details:
        Correct TOTP code on /login/2fa creates the session and redirects to home.
    """
    import pyotp
    from flask_app.models.user import User

    with twofa_app.app_context():
        user = User(username="totpchalloginuser", role="user")
        user.set_password("pass")
        secret = pyotp.random_base32()
        user.totp_secret = secret
        user.totp_enabled = True
        db.session.add(user)
        db.session.commit()

    client = twofa_app.test_client()
    _login(client, "totpchalloginuser", "pass")

    code = pyotp.TOTP(secret).now()
    with client:
        response = client.post("/login/2fa", data={"code": code})
        from flask import session
        assert response.status_code == 302
        assert "_user_id" in session


def test_totp_challenge_wrong_code_returns_401(twofa_app):
    """
    Input: twofa_app fixture
    Output: None
    Details:
        Wrong TOTP code returns 401 and does not create a session.
    """
    import pyotp
    from flask_app.models.user import User

    with twofa_app.app_context():
        user = User(username="totpwrongcode", role="user")
        user.set_password("pass")
        user.totp_secret = pyotp.random_base32()
        user.totp_enabled = True
        db.session.add(user)
        db.session.commit()

    client = twofa_app.test_client()
    _login(client, "totpwrongcode", "pass")

    with client:
        response = client.post("/login/2fa", data={"code": "000000"})
        from flask import session
        assert response.status_code == 401
        assert "_user_id" not in session


def test_totp_disable_clears_secret(twofa_app):
    """
    Input: twofa_app fixture
    Output: None
    Details:
        POST /settings/2fa/disable with the correct current password clears
        totp_secret and sets totp_enabled=False.
    """
    import pyotp
    from flask_app.models.user import User

    with twofa_app.app_context():
        user = User(username="totpdisableuser", role="user")
        user.set_password("pass")
        user.totp_secret = pyotp.random_base32()
        user.totp_enabled = True
        db.session.add(user)
        db.session.commit()

    client = twofa_app.test_client()
    # Log in via TOTP flow
    _login(client, "totpdisableuser", "pass")
    totp_secret_snap = None
    with twofa_app.app_context():
        u = db.session.execute(db.select(User).filter_by(username="totpdisableuser")).scalar_one()
        totp_secret_snap = u.totp_secret
    code = pyotp.TOTP(totp_secret_snap).now()
    client.post("/login/2fa", data={"code": code})

    response = client.post("/settings/2fa/disable", data={"current_password": "pass"})
    assert response.status_code == 302

    with twofa_app.app_context():
        user = db.session.execute(
            db.select(User).filter_by(username="totpdisableuser")
        ).scalar_one()
        assert user.totp_enabled is False
        assert user.totp_secret is None


# ── WebAuthn tests ────────────────────────────────────────────────────────────

def test_webauthn_registration_challenge_contains_required_fields(twofa_app):
    """
    Input: twofa_app fixture
    Output: None
    Details:
        GET /settings/2fa/webauthn/register returns JSON with 'challenge',
        'rp', and 'user' fields.
    """
    from flask_app.models.user import User

    with twofa_app.app_context():
        user = User(username="wkregchallengeuser", role="user")
        user.set_password("pass")
        db.session.add(user)
        db.session.commit()

    client = twofa_app.test_client()
    _login(client, "wkregchallengeuser", "pass")

    with patch("webauthn.generate_registration_options") as mock_gen:
        mock_opts = MagicMock()
        mock_opts.challenge = b"fake-challenge-bytes"
        mock_opts.rp.id = "localhost"
        mock_opts.rp.name = "SHSE Test"
        mock_opts.user.id = b"1"
        mock_opts.user.name = "wkregchallengeuser"
        mock_opts.user.display_name = "wkregchallengeuser"
        mock_opts.pub_key_cred_params = []
        mock_opts.timeout = 60000
        mock_gen.return_value = mock_opts

        response = client.get("/settings/2fa/webauthn/register")

    assert response.status_code == 200
    data = response.get_json()
    assert "challenge" in data
    assert "rp" in data
    assert "user" in data


def test_webauthn_registration_stores_credential(twofa_app):
    """
    Input: twofa_app fixture
    Output: None
    Details:
        POST /settings/2fa/webauthn/register with mocked verify_registration_response
        stores a WebAuthnCredential row.
    """
    from flask_app.models.user import User
    from flask_app.models.webauthn_credential import WebAuthnCredential

    with twofa_app.app_context():
        user = User(username="wkregstoreuser", role="user")
        user.set_password("pass")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    client = twofa_app.test_client()
    _login(client, "wkregstoreuser", "pass")

    # Seed the session challenge
    with client.session_transaction() as sess:
        sess["webauthn_reg_challenge"] = base64.urlsafe_b64encode(b"fake-challenge").rstrip(b"=").decode()

    mock_verification = MagicMock()
    mock_verification.credential_id = b"\x01\x02\x03\x04"
    mock_verification.credential_public_key = b"\x05\x06\x07\x08"
    mock_verification.sign_count = 0
    mock_verification.aaguid = None

    body = {
        "id": "AQIDBA",
        "rawId": "AQIDBA",
        "type": "public-key",
        "name": "Test Key",
        "response": {
            "attestationObject": base64.urlsafe_b64encode(b"attest").rstrip(b"=").decode(),
            "clientDataJSON": base64.urlsafe_b64encode(b"client").rstrip(b"=").decode(),
        },
    }

    with patch("webauthn.verify_registration_response", return_value=mock_verification):
        with patch("webauthn.helpers.structs.RegistrationCredential") as mock_reg_cred_cls:
            mock_reg_cred_cls.parse_raw.return_value = MagicMock()
            response = client.post(
                "/settings/2fa/webauthn/register",
                json=body,
                content_type="application/json",
            )

    assert response.status_code == 200
    data = response.get_json()
    assert data.get("ok") is True

    with twofa_app.app_context():
        cred = db.session.execute(
            db.select(WebAuthnCredential).filter_by(user_id=user_id)
        ).scalar_one_or_none()
        assert cred is not None
        assert cred.credential_id == b"\x01\x02\x03\x04"


def test_webauthn_login_redirects_to_challenge(twofa_app):
    """
    Input: twofa_app fixture
    Output: None
    Details:
        A user with a registered WebAuthn credential (and TOTP disabled) must
        be redirected to /login/webauthn after correct password entry.
    """
    from flask_app.models.user import User
    from flask_app.models.webauthn_credential import WebAuthnCredential

    with twofa_app.app_context():
        user = User(username="wkloginuser", role="user")
        user.set_password("pass")
        db.session.add(user)
        db.session.flush()
        cred = WebAuthnCredential(
            credential_id=b"\xde\xad\xbe\xef",
            user_id=user.id,
            public_key=b"\xca\xfe",
            sign_count=0,
        )
        db.session.add(cred)
        db.session.commit()

    client = twofa_app.test_client()
    response = _login(client, "wkloginuser", "pass")
    assert response.status_code == 302
    assert "/login/webauthn" in response.headers["Location"]


def test_webauthn_authentication_verifies_and_logs_in(twofa_app):
    """
    Input: twofa_app fixture
    Output: None
    Details:
        POST /login/webauthn with mocked verify_authentication_response updates
        sign_count and calls login_user (session contains _user_id).
    """
    from flask_app.models.user import User
    from flask_app.models.webauthn_credential import WebAuthnCredential

    cred_id_bytes = b"\xde\xad\xbe\xef"

    with twofa_app.app_context():
        user = User(username="wkauthuser", role="user")
        user.set_password("pass")
        db.session.add(user)
        db.session.flush()
        cred = WebAuthnCredential(
            credential_id=cred_id_bytes,
            user_id=user.id,
            public_key=b"\xca\xfe",
            sign_count=5,
        )
        db.session.add(cred)
        db.session.commit()
        user_id = user.id

    client = twofa_app.test_client()
    _login(client, "wkauthuser", "pass")

    # Seed session challenge and pre_2fa_user_id
    with client.session_transaction() as sess:
        sess["webauthn_challenge"] = base64.urlsafe_b64encode(b"test-challenge").rstrip(b"=").decode()

    mock_verification = MagicMock()
    mock_verification.new_sign_count = 6

    body = {
        "id": base64.urlsafe_b64encode(cred_id_bytes).rstrip(b"=").decode(),
        "rawId": base64.urlsafe_b64encode(cred_id_bytes).rstrip(b"=").decode(),
        "type": "public-key",
        "response": {
            "authenticatorData": base64.urlsafe_b64encode(b"adata").rstrip(b"=").decode(),
            "clientDataJSON": base64.urlsafe_b64encode(b"cdj").rstrip(b"=").decode(),
            "signature": base64.urlsafe_b64encode(b"sig").rstrip(b"=").decode(),
            "userHandle": None,
        },
    }

    with patch("webauthn.verify_authentication_response", return_value=mock_verification):
        with patch("webauthn.helpers.structs.AuthenticationCredential") as mock_auth_cred_cls:
            mock_auth_cred = MagicMock()
            mock_auth_cred.raw_id = cred_id_bytes
            mock_auth_cred_cls.parse_raw.return_value = mock_auth_cred
            with client:
                response = client.post(
                    "/login/webauthn",
                    json=body,
                    content_type="application/json",
                )
                from flask import session
                assert response.status_code == 200
                assert "_user_id" in session

    with twofa_app.app_context():
        updated_cred = db.session.execute(
            db.select(WebAuthnCredential).filter_by(user_id=user_id)
        ).scalar_one()
        assert updated_cred.sign_count == 6


def test_webauthn_mismatched_challenge_returns_401(twofa_app):
    """
    Input: twofa_app fixture
    Output: None
    Details:
        POST /login/webauthn where verify_authentication_response raises an
        exception (simulating mismatched challenge) returns 401.
    """
    from flask_app.models.user import User
    from flask_app.models.webauthn_credential import WebAuthnCredential

    cred_id_bytes = b"\xba\xad\xf0\x0d"

    with twofa_app.app_context():
        user = User(username="wkmismatchuser", role="user")
        user.set_password("pass")
        db.session.add(user)
        db.session.flush()
        cred = WebAuthnCredential(
            credential_id=cred_id_bytes,
            user_id=user.id,
            public_key=b"\xca\xfe",
            sign_count=0,
        )
        db.session.add(cred)
        db.session.commit()

    client = twofa_app.test_client()
    _login(client, "wkmismatchuser", "pass")

    with client.session_transaction() as sess:
        sess["webauthn_challenge"] = base64.urlsafe_b64encode(b"test-challenge").rstrip(b"=").decode()

    body = {"id": "badf00d", "rawId": "badf00d", "type": "public-key", "response": {}}

    with patch("webauthn.verify_authentication_response",
               side_effect=Exception("challenge mismatch")):
        with patch("webauthn.helpers.structs.AuthenticationCredential") as mock_cls:
            mock_cred = MagicMock()
            mock_cred.raw_id = cred_id_bytes
            mock_cls.parse_raw.return_value = mock_cred
            response = client.post(
                "/login/webauthn",
                json=body,
                content_type="application/json",
            )

    assert response.status_code == 401


def test_webauthn_remove_credential_deletes_row(twofa_app):
    """
    Input: twofa_app fixture
    Output: None
    Details:
        POST /settings/2fa/webauthn/<id>/remove with correct password removes
        the credential row. A subsequent login skips WebAuthn challenge.
    """
    from flask_app.models.user import User
    from flask_app.models.webauthn_credential import WebAuthnCredential

    with twofa_app.app_context():
        user = User(username="wkremoveuser", role="user")
        user.set_password("pass")
        db.session.add(user)
        db.session.flush()
        cred = WebAuthnCredential(
            credential_id=b"\xaa\xbb\xcc\xdd",
            user_id=user.id,
            public_key=b"\xca\xfe",
            sign_count=0,
        )
        db.session.add(cred)
        db.session.commit()
        cred_db_id = cred.id
        user_id = user.id

    client = twofa_app.test_client()
    _login(client, "wkremoveuser", "pass")
    # Must complete WebAuthn challenge first to establish session
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess.pop("pre_2fa_user_id", None)

    response = client.post(
        f"/settings/2fa/webauthn/{cred_db_id}/remove",
        data={"current_password": "pass"},
    )
    assert response.status_code == 302

    with twofa_app.app_context():
        cred = db.session.execute(
            db.select(WebAuthnCredential).filter_by(id=cred_db_id)
        ).scalar_one_or_none()
        assert cred is None

    # Next login should not redirect to WebAuthn challenge
    client2 = twofa_app.test_client()
    response2 = _login(client2, "wkremoveuser", "pass")
    assert response2.status_code == 302
    assert "/login/webauthn" not in response2.headers.get("Location", "")


def test_duplicate_credential_id_is_rejected(twofa_app):
    """
    Input:  Two WebAuthnCredential rows with the same credential_id bytes
    Output: IntegrityError (or OperationalError) raised on flush — unique constraint enforced
    Details:
        credential_id has unique=True on the DB column. Attempting to insert
        a second row with the same bytes must raise a DB integrity error.
        This exercises the constraint at the DB level, not just the application layer.
    """
    import sqlalchemy.exc
    from flask_app.models.user import User
    from flask_app.models.webauthn_credential import WebAuthnCredential

    with twofa_app.app_context():
        user = User(username="wkdupuser", role="user")
        user.set_password("pass")
        db.session.add(user)
        db.session.flush()

        cred1 = WebAuthnCredential(
            credential_id=b"\xde\xad\xbe\xef",
            user_id=user.id,
            public_key=b"\x01\x02",
            sign_count=0,
        )
        db.session.add(cred1)
        db.session.flush()

        cred2 = WebAuthnCredential(
            credential_id=b"\xde\xad\xbe\xef",
            user_id=user.id,
            public_key=b"\x03\x04",
            sign_count=0,
        )
        db.session.add(cred2)
        with pytest.raises((sqlalchemy.exc.IntegrityError, sqlalchemy.exc.OperationalError)):
            db.session.flush()
        db.session.rollback()


if __name__ == "__main__":
    pass
