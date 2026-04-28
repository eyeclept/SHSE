"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for Epic 4 (Authentication): password hashing, login, logout,
    registration, first-run setup, RBAC, and SSO.
"""
# Imports
import os
from unittest.mock import patch
import pytest
from flask import Flask
from flask_app import db, login_manager, oauth
from flask_app.models.user import User

# Globals
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "templates")
_STATIC_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "static")

# Globals

# Functions
@pytest.fixture
def sqlite_app():
    """
    Input: None
    Output: Flask test app with in-memory SQLite DB
    Details:
        Creates a minimal Flask app with SQLite to avoid requiring MariaDB.
        Does not call create_app() so the MariaDB engine is never initialised.
        Imports all models before create_all() so their tables are registered.
    """
    # import all models so their tables appear in db.metadata
    from flask_app.models.search_history import SearchHistory  # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget  # noqa: F401
    from flask_app.models.crawl_job import CrawlJob            # noqa: F401

    # import blueprints (needed for url_for and route resolution in route tests)
    from flask_app.routes.auth import auth_bp
    from flask_app.routes.search import search_bp
    from flask_app.routes.admin import admin_bp

    test_app = Flask("test_auth", template_folder=_TEMPLATE_DIR, static_folder=_STATIC_DIR)
    test_app.config["TESTING"] = True
    test_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    test_app.config["SECRET_KEY"] = "test-secret"
    db.init_app(test_app)
    login_manager.init_app(test_app)
    test_app.register_blueprint(auth_bp)
    test_app.register_blueprint(search_bp)
    test_app.register_blueprint(admin_bp, url_prefix="/admin")

    with test_app.app_context():
        db.create_all()
        yield test_app
        db.drop_all()


def test_password_hash(sqlite_app):
    """
    Input: sqlite_app fixture (provides active app context)
    Output: None
    Details:
        Verifies that set_password produces different hashes for the same
        plaintext (bcrypt random salt), and that check_password correctly
        validates a matching password and rejects a wrong one.
    """
    with sqlite_app.app_context():
        user1 = User(username="alice", role="user")
        user1.set_password("s3cr3t!")

        user2 = User(username="bob", role="user")
        user2.set_password("s3cr3t!")

        # Same plaintext must produce different hashes (unique salts)
        assert user1.password_hash != user2.password_hash

        # Correct password must verify
        assert user1.check_password("s3cr3t!")

        # Wrong password must not verify
        assert not user1.check_password("wrong")

        # Unset password_hash must return False
        user3 = User(username="charlie", role="user")
        assert not user3.check_password("anything")


def test_login(sqlite_app):
    """
    Input: sqlite_app fixture
    Output: None
    Details:
        Valid credentials must redirect (302) and set the Flask-Login session.
        Invalid credentials must return 401.
    """
    with sqlite_app.app_context():
        user = User(username="loginuser", role="user")
        user.set_password("loginpass")
        db.session.add(user)
        db.session.commit()

    client = sqlite_app.test_client()

    # valid credentials — expect redirect and session cookie
    with client:
        response = client.post(
            "/login", data={"username": "loginuser", "password": "loginpass"}
        )
        from flask import session
        assert response.status_code == 302
        assert "_user_id" in session

    # invalid password — expect 401
    response = client.post(
        "/login", data={"username": "loginuser", "password": "wrong"}
    )
    assert response.status_code == 401

    # unknown username — expect 401
    response = client.post(
        "/login", data={"username": "nobody", "password": "anything"}
    )
    assert response.status_code == 401


@pytest.fixture
def sso_app():
    """
    Input: None
    Output: Flask test app with SSO_ENABLED=True and a mock OIDC client
    Details:
        Registers 'oidc' with explicit endpoints (no server_metadata_url fetch).
        Shares the module-level oauth instance; re-registers on each test run.
    """
    from flask_app.models.search_history import SearchHistory  # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget  # noqa: F401
    from flask_app.models.crawl_job import CrawlJob            # noqa: F401
    from flask_app.routes.auth import auth_bp
    from flask_app.routes.search import search_bp
    from flask_app.routes.admin import admin_bp

    test_app = Flask("test_sso", template_folder=_TEMPLATE_DIR, static_folder=_STATIC_DIR)
    test_app.config["TESTING"] = True
    test_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    test_app.config["SECRET_KEY"] = "test-secret-sso"
    test_app.config["SSO_ENABLED"] = True

    db.init_app(test_app)
    login_manager.init_app(test_app)
    oauth.init_app(test_app)
    # Register with explicit endpoints so no HTTP fetch occurs at registration time
    oauth.register(
        name="oidc",
        client_id="test-client-id",
        client_secret="test-client-secret",
        authorize_url="http://fake-provider/authorize",
        access_token_url="http://fake-provider/token",
        client_kwargs={"scope": "openid email profile"},
    )
    test_app.register_blueprint(auth_bp)
    test_app.register_blueprint(search_bp)
    test_app.register_blueprint(admin_bp, url_prefix="/admin")

    with test_app.app_context():
        db.create_all()
        yield test_app
        db.drop_all()


def test_sso(sso_app):
    """
    Input: sso_app fixture
    Output: None
    Details:
        GET /sso/login must redirect to the OIDC provider's authorize URL.
        GET /sso/callback with a mocked token exchange must create a user
        keyed on 'sub' and redirect to the search page.
    """
    client = sso_app.test_client()

    # /sso/login must redirect to the fake OIDC provider
    response = client.get("/sso/login")
    assert response.status_code == 302
    assert "fake-provider" in response.headers["Location"]

    # /sso/callback with mocked authorize_access_token
    mock_token = {
        "access_token": "fake-access-token",
        "userinfo": {
            "sub": "sso-sub-001",
            "preferred_username": "ssouser",
            "email": "ssouser@example.com",
        },
    }
    with patch.object(oauth.oidc, "authorize_access_token", return_value=mock_token):
        response = client.get("/sso/callback")
    assert response.status_code == 302

    # user must be created with correct sso_identity and role
    with sso_app.app_context():
        user = db.session.execute(
            db.select(User).filter_by(sso_identity="sso-sub-001")
        ).scalar_one_or_none()
        assert user is not None
        assert user.username == "ssouser"
        assert user.role == "user"

    # second callback with same sub must reuse existing user, not create a duplicate
    with patch.object(oauth.oidc, "authorize_access_token", return_value=mock_token):
        response = client.get("/sso/callback")
    assert response.status_code == 302

    with sso_app.app_context():
        count = db.session.execute(
            db.select(User).filter_by(sso_identity="sso-sub-001")
        ).scalars().all()
        assert len(count) == 1


def test_sso_role_mapping(sso_app):
    """
    Input: sso_app fixture
    Output: None
    Details:
        User in the admin group must be created with role 'admin'.
        User not in the admin group must receive role 'user'.
        Re-login without admin group must downgrade an existing admin to 'user'.
    """
    client = sso_app.test_client()

    # groups contains the admin group → role must be admin
    mock_admin_token = {
        "access_token": "fake-access-token",
        "userinfo": {
            "sub": "sso-role-admin",
            "preferred_username": "adminviagroup",
            "groups": ["admin"],
        },
    }
    with patch.object(oauth.oidc, "authorize_access_token", return_value=mock_admin_token):
        response = client.get("/sso/callback")
    assert response.status_code == 302

    with sso_app.app_context():
        user = db.session.execute(
            db.select(User).filter_by(sso_identity="sso-role-admin")
        ).scalar_one_or_none()
        assert user is not None
        assert user.role == "admin"

    # groups does not contain admin group → role must be user
    mock_user_token = {
        "access_token": "fake-access-token",
        "userinfo": {
            "sub": "sso-role-regular",
            "preferred_username": "regularviasso",
            "groups": ["employees"],
        },
    }
    with patch.object(oauth.oidc, "authorize_access_token", return_value=mock_user_token):
        response = client.get("/sso/callback")
    assert response.status_code == 302

    with sso_app.app_context():
        user = db.session.execute(
            db.select(User).filter_by(sso_identity="sso-role-regular")
        ).scalar_one_or_none()
        assert user is not None
        assert user.role == "user"

    # existing admin re-logs in without admin group → role must be downgraded to user
    mock_demoted_token = {
        "access_token": "fake-access-token",
        "userinfo": {
            "sub": "sso-role-admin",
            "preferred_username": "adminviagroup",
            "groups": [],
        },
    }
    with patch.object(oauth.oidc, "authorize_access_token", return_value=mock_demoted_token):
        response = client.get("/sso/callback")
    assert response.status_code == 302

    with sso_app.app_context():
        user = db.session.execute(
            db.select(User).filter_by(sso_identity="sso-role-admin")
        ).scalar_one_or_none()
        assert user.role == "user"


def test_admin_access(sqlite_app):
    """
    Input: sqlite_app fixture
    Output: None
    Details:
        Unauthenticated request to /admin/ must redirect to login (302).
        Authenticated non-admin must receive 403.
        Authenticated admin must not receive 403 (stub returns 500, which is acceptable).
    """
    with sqlite_app.app_context():
        regular = User(username="regularuser", role="user")
        regular.set_password("pass")
        admin = User(username="adminuser2", role="admin")
        admin.set_password("pass")
        db.session.add_all([regular, admin])
        db.session.commit()

    client = sqlite_app.test_client()

    # unauthenticated — expect redirect to login
    response = client.get("/admin/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    # authenticated non-admin — expect 403
    client.post("/login", data={"username": "regularuser", "password": "pass"})
    response = client.get("/admin/")
    assert response.status_code == 403

    # log out then log in as admin — decorator must pass through (stub returns None → 500)
    client.get("/logout")
    client.post("/login", data={"username": "adminuser2", "password": "pass"})
    sqlite_app.config["PROPAGATE_EXCEPTIONS"] = False
    response = client.get("/admin/")
    sqlite_app.config["PROPAGATE_EXCEPTIONS"] = True
    assert response.status_code != 403


def test_setup(sqlite_app):
    """
    Input: sqlite_app fixture
    Output: None
    Details:
        When no admin exists, POST /setup creates an admin user and redirects to login.
        When an admin already exists, GET /setup redirects to login without creating a user.
    """
    client = sqlite_app.test_client()

    # no admin yet — form submission must create admin and redirect
    response = client.post(
        "/setup", data={"username": "adminuser", "password": "adminpass"}
    )
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    with sqlite_app.app_context():
        admin = db.session.execute(
            db.select(User).filter_by(username="adminuser")
        ).scalar_one_or_none()
        assert admin is not None
        assert admin.role == "admin"
        assert admin.check_password("adminpass")

    # admin already exists — GET /setup must redirect to login without another creation
    response = client.get("/setup")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    with sqlite_app.app_context():
        count = db.session.execute(
            db.select(User).filter_by(role="admin")
        ).scalars().all()
        assert len(count) == 1


def test_register(sqlite_app):
    """
    Input: sqlite_app fixture
    Output: None
    Details:
        Valid registration must create a user row with role 'user' and redirect (302).
        Duplicate username must return 400.
        Missing fields must return 400.
    """
    client = sqlite_app.test_client()

    # valid registration — expect redirect and user row in DB
    response = client.post(
        "/register", data={"username": "newuser", "password": "newpass"}
    )
    assert response.status_code == 302

    with sqlite_app.app_context():
        user = db.session.execute(
            db.select(User).filter_by(username="newuser")
        ).scalar_one_or_none()
        assert user is not None
        assert user.role == "user"
        assert user.check_password("newpass")

    # duplicate username — expect 400
    response = client.post(
        "/register", data={"username": "newuser", "password": "other"}
    )
    assert response.status_code == 400

    # missing password — expect 400
    response = client.post("/register", data={"username": "incomplete", "password": ""})
    assert response.status_code == 400


def test_toggle_theme(sqlite_app):
    """
    Input: sqlite_app fixture
    Output: None
    Details:
        POST /theme flips session['theme'] from light to dark and back.
        Unauthenticated access is allowed (theme is a user preference, not gated).
        Response redirects to referrer or to / when no referrer is set.
    """
    client = sqlite_app.test_client()

    with client:
        # Default (no theme set) → should become dark
        response = client.post("/theme")
        from flask import session
        assert response.status_code == 302
        assert session.get("theme") == "dark"

    with client:
        # dark → should become light
        with client.session_transaction() as sess:
            sess["theme"] = "dark"
        response = client.post("/theme")
        from flask import session
        assert response.status_code == 302
        assert session.get("theme") == "light"

    # Redirects to Referer header when present
    with client:
        response = client.post("/theme", headers={"Referer": "http://localhost/search"})
        assert response.status_code == 302
        assert "/search" in response.headers["Location"]


def test_logout(sqlite_app):
    """
    Input: sqlite_app fixture
    Output: None
    Details:
        Logs in a user then calls GET /logout.
        Expects a 302 redirect and session cleared (_user_id absent).
    """
    with sqlite_app.app_context():
        user = User(username="logoutuser", role="user")
        user.set_password("logoutpass")
        db.session.add(user)
        db.session.commit()

    client = sqlite_app.test_client()

    with client:
        client.post("/login", data={"username": "logoutuser", "password": "logoutpass"})
        response = client.get("/logout")
        from flask import session
        assert response.status_code == 302
        assert "_user_id" not in session


def test_password_change(sqlite_app):
    """
    Input: sqlite_app fixture
    Output: None
    Details:
        Valid password change must redirect (302) with no server error.
        Blank new password must return 400 with user-visible error message.
        Mismatched confirmation must return 400 with user-visible error message.
    """
    with sqlite_app.app_context():
        user = User(username="pwuser", role="user")
        user.set_password("oldpassword1")
        db.session.add(user)
        db.session.commit()

    client = sqlite_app.test_client()
    client.post("/login", data={"username": "pwuser", "password": "oldpassword1"})

    # blank new password — must return 400
    response = client.post(
        "/settings/password",
        data={"current_password": "oldpassword1", "new_password": "", "confirm_password": ""},
    )
    assert response.status_code == 400

    # mismatched confirmation — must return 400
    response = client.post(
        "/settings/password",
        data={
            "current_password": "oldpassword1",
            "new_password": "newpassword1",
            "confirm_password": "differentpassword1",
        },
    )
    assert response.status_code == 400

    # valid change — must redirect with no server error
    response = client.post(
        "/settings/password",
        data={
            "current_password": "oldpassword1",
            "new_password": "newpassword1",
            "confirm_password": "newpassword1",
        },
    )
    assert response.status_code == 302

    with sqlite_app.app_context():
        user = db.session.execute(
            db.select(User).filter_by(username="pwuser")
        ).scalar_one_or_none()
        assert user.check_password("newpassword1")


if __name__ == "__main__":
    pass
