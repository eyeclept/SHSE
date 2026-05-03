"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for Epic 22 (System Reset): CLI reset-admin-password logic.
    Tests call _reset_admin_password_impl directly (not subprocess) so no
    Docker stack is required.
"""
# Imports
import os
import pytest
from flask import Flask
from flask_app import db

# Globals
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "templates")
_STATIC_DIR   = os.path.join(_PROJECT_ROOT, "flask_app", "static")


# Functions
@pytest.fixture
def sqlite_app():
    """
    Input: None
    Output: Flask test app with in-memory SQLite DB
    Details:
        Minimal Flask app without MariaDB. Imports all models before
        create_all() so their tables appear in db.metadata.
    """
    from flask_app.models.user import User                      # noqa: F401
    from flask_app.models.search_history import SearchHistory  # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget  # noqa: F401
    from flask_app.models.crawl_job import CrawlJob            # noqa: F401

    test_app = Flask("test_reset", template_folder=_TEMPLATE_DIR, static_folder=_STATIC_DIR)
    test_app.config["TESTING"] = True
    test_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    test_app.config["SECRET_KEY"] = "test-secret"
    db.init_app(test_app)

    with test_app.app_context():
        db.create_all()
        yield test_app
        db.drop_all()


def test_reset_admin_password_valid(sqlite_app):
    """
    Input: sqlite_app fixture
    Output: None
    Details:
        Creates an admin user, resets the password via _reset_admin_password_impl,
        and verifies the new bcrypt hash validates correctly.
    """
    from flask_app.models.user import User
    from cli import _reset_admin_password_impl

    with sqlite_app.app_context():
        admin = User(username="testadmin", role="admin")
        admin.set_password("oldpassword")
        db.session.add(admin)
        db.session.commit()

        _reset_admin_password_impl(db.session, "testadmin", "newpassword123")

        updated = db.session.query(User).filter_by(username="testadmin").first()
        assert updated.check_password("newpassword123")
        assert not updated.check_password("oldpassword")


def test_reset_admin_password_wrong_role(sqlite_app):
    """
    Input: sqlite_app fixture
    Output: None
    Details:
        Creates a regular user and verifies _reset_admin_password_impl
        raises SystemExit with a non-zero code.
    """
    from flask_app.models.user import User
    from cli import _reset_admin_password_impl

    with sqlite_app.app_context():
        regular = User(username="regularuser", role="user")
        regular.set_password("pass")
        db.session.add(regular)
        db.session.commit()

        with pytest.raises(SystemExit) as exc_info:
            _reset_admin_password_impl(db.session, "regularuser", "newpass")
        assert exc_info.value.code != 0


def test_reset_admin_password_nonexistent(sqlite_app):
    """
    Input: sqlite_app fixture
    Output: None
    Details:
        Verifies _reset_admin_password_impl raises SystemExit for a
        username that does not exist in the DB.
    """
    from cli import _reset_admin_password_impl

    with sqlite_app.app_context():
        with pytest.raises(SystemExit) as exc_info:
            _reset_admin_password_impl(db.session, "ghostuser", "anypass")
        assert exc_info.value.code != 0
