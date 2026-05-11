"""
Author: Richard Baldwin
Date:   2026
Email:  eyeclept@pm.me

Description:
    Shared pytest fixtures for the SHSE test suite.
    Provides base_url for pytest-playwright and session-scoped credential
    fixtures that seed a test admin (via MariaDB) and a test regular user
    (via HTTP /register) before Playwright integration tests run.
"""
# Imports
import logging
import os

import pymysql
import pytest
import requests
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

# Globals
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

logger = logging.getLogger(__name__)

_BASE_URL = "http://localhost:5000"
_TEST_ADMIN = "pw_test_admin"
_TEST_ADMIN_PW = "Playwright#Admin1"
_TEST_USER = "pw_test_user"
_TEST_USER_PW = "Playwright#User1"


# Functions
def _server_up():
    """
    Input: None
    Output: bool — True if Flask server is reachable at localhost:5000
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
    Output: pymysql connection using MARIADB_* env vars from .env
    """
    return pymysql.connect(
        host=os.environ.get("MARIADB_HOST", "localhost"),
        port=int(os.environ.get("MARIADB_PORT", 3306)),
        user=os.environ.get("MARIADB_USER", "shse_user"),
        password=os.environ.get("MARIADB_PASSWORD", ""),
        database=os.environ.get("MARIADB_DB", "shse"),
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
            cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                (_TEST_ADMIN, generate_password_hash(_TEST_ADMIN_PW), "admin"),
            )
        yield {"username": _TEST_ADMIN, "password": _TEST_ADMIN_PW}
    finally:
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE username = %s", (_TEST_ADMIN,))
        except Exception as e:
            logger.warning("Admin test-user cleanup failed: %s", e)
        conn.close()


@pytest.fixture(scope="session")
def test_user_creds():
    """
    Input: None
    Output: dict {"username": str, "password": str} for a seeded regular user
    Details:
        Registers the test user via HTTP POST /register. A 400 response
        (username already taken) is treated as success — the user exists.
    """
    try:
        r = requests.post(
            f"{_BASE_URL}/register",
            data={"username": _TEST_USER, "password": _TEST_USER_PW},
            timeout=5,
            allow_redirects=False,
        )
        if r.status_code not in (302, 400):
            logger.warning("Unexpected /register status %s for test user", r.status_code)
    except Exception as e:
        logger.warning("Failed to register Playwright test user: %s", e)
    yield {"username": _TEST_USER, "password": _TEST_USER_PW}
