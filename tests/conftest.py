"""
Author: Richard Baldwin
Date:   2026
Email:  eyeclept@pm.me

Description:
    Shared pytest fixtures for the SHSE test suite.
    Provides base_url for pytest-playwright and session-scoped credential
    fixtures that seed a test admin (via MariaDB) and a test regular user
    (via HTTP /register) before Playwright integration tests run.

    All connection parameters are read from config.ini via flask_app.config.Config
    so tests use the same configuration as the application — no hardcoded values.
    SHSE_TEST_URL overrides the Flask base URL for the test session (defaults to
    http://localhost:5000, the internal address of the Flask container on the app VM).
"""
# Imports
import logging
import os

import bcrypt
import pymysql
import pytest
import requests
from dotenv import load_dotenv

# Globals
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from flask_app.config import Config  # noqa: E402 — must load .env first

logger = logging.getLogger(__name__)

_BASE_URL  = os.environ.get("SHSE_TEST_URL", "http://localhost:5000")
_TEST_ADMIN   = "pw_test_admin"
_TEST_ADMIN_PW = "Playwright#Admin1"
_TEST_USER    = "pw_test_user"
_TEST_USER_PW = "Playwright#User1"


# Functions
def _server_up():
    """
    Input: None
    Output: bool — True if Flask server is reachable at _BASE_URL
    """
    try:
        requests.get(_BASE_URL, timeout=3)
        return True
    except Exception:
        logger.warning("Flask server not reachable at %s", _BASE_URL)
        return False


def _db_conn():
    """
    Input: None
    Output: pymysql connection using settings from config.ini and secrets from .env
    Details:
        Connection parameters come from flask_app.config.Config which reads
        config.ini (for host/port/user/db) and .env (for password).
    """
    return pymysql.connect(
        host=Config.MARIADB_HOST,
        port=Config.MARIADB_PORT,
        user=Config.MARIADB_USER,
        password=Config.MARIADB_PASSWORD,
        database=Config.MARIADB_DB,
        autocommit=True,
    )


@pytest.fixture(scope="session")
def base_url():
    """
    Input: None
    Output: str — Flask base URL consumed by pytest-playwright's page fixture
    """
    return _BASE_URL


@pytest.fixture(scope="session")
def test_admin_creds():
    """
    Input: None
    Output: dict {"username": str, "password": str} for a seeded admin account
    Details:
        Inserts a test admin directly into MariaDB (works whether or not an
        admin already exists). Deletes the row after the session ends.
    """
    conn = _db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE username = %s", (_TEST_ADMIN,))
            pw_hash = bcrypt.hashpw(_TEST_ADMIN_PW.encode(), bcrypt.gensalt()).decode()
            cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                (_TEST_ADMIN, pw_hash, "admin"),
            )
        yield {"username": _TEST_ADMIN, "password": _TEST_ADMIN_PW}
    finally:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE username = %s", (_TEST_ADMIN,))
                row = cur.fetchone()
                if row:
                    cur.execute("DELETE FROM search_history WHERE user_id = %s", (row[0],))
                    cur.execute("DELETE FROM users WHERE id = %s", (row[0],))
        except Exception as e:
            logger.warning("Admin test-user cleanup failed: %s", e)
        conn.close()


@pytest.fixture(scope="session")
def test_user_creds():
    """
    Input: None
    Output: dict {"username": str, "password": str} for a seeded regular user
    Details:
        Inserts the test user directly into MariaDB (same pattern as
        test_admin_creds). Using HTTP /register would fail because CSRF
        protection blocks unauthenticated POST requests without a token.
        Deletes the row after the session ends.
    """
    conn = _db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE username = %s", (_TEST_USER,))
            pw_hash = bcrypt.hashpw(_TEST_USER_PW.encode(), bcrypt.gensalt()).decode()
            cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                (_TEST_USER, pw_hash, "user"),
            )
        yield {"username": _TEST_USER, "password": _TEST_USER_PW}
    finally:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE username = %s", (_TEST_USER,))
                row = cur.fetchone()
                if row:
                    cur.execute("DELETE FROM search_history WHERE user_id = %s", (row[0],))
                    cur.execute("DELETE FROM users WHERE id = %s", (row[0],))
        except Exception as e:
            logger.warning("Test-user cleanup failed: %s", e)
        conn.close()
