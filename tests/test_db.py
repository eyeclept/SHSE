"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for Epic 3 (Database): table existence, schema correctness, and
    foreign key enforcement.  Requires the MariaDB Docker container to be running.
"""
# Imports
import os

import pymysql
import pytest
from dotenv import load_dotenv

# Globals
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# Functions
def _get_conn():
    """
    Input: None
    Output: pymysql connection
    Details:
        Opens a connection to the MariaDB container using values from .env.
    """
    return pymysql.connect(
        host=os.environ.get("MARIADB_HOST", "localhost"),
        port=int(os.environ.get("MARIADB_PORT", 3306)),
        user=os.environ.get("MARIADB_USER", "shse_user"),
        password=os.environ.get("MARIADB_PASSWORD", ""),
        database=os.environ.get("MARIADB_DB", "shse"),
        autocommit=False,
    )


def test_all_tables_exist():
    """
    Input: None
    Output: None
    Details:
        Connects to MariaDB and verifies that all four application tables are present.
    """
    conn = _get_conn()
    with conn.cursor() as cursor:
        cursor.execute("SHOW TABLES")
        tables = {row[0] for row in cursor.fetchall()}
    conn.close()
    assert "users" in tables
    assert "search_history" in tables
    assert "crawler_targets" in tables
    assert "crawl_jobs" in tables


def test_users_schema():
    """
    Input: None
    Output: None
    Details:
        Verifies that the users table contains all expected columns.
    """
    conn = _get_conn()
    with conn.cursor() as cursor:
        cursor.execute("DESCRIBE users")
        cols = {row[0] for row in cursor.fetchall()}
    conn.close()
    for col in ("id", "username", "password_hash", "role", "sso_identity"):
        assert col in cols, f"Column {col!r} missing from users table"


def test_search_history_fk_enforced():
    """
    Input: None
    Output: None
    Details:
        Attempts to insert a search_history row referencing a nonexistent user_id.
        Expects pymysql.err.IntegrityError, confirming the FK is enforced.
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO search_history (user_id, query, timestamp) VALUES (%s, %s, NOW())",
                (999999, "fk-test"),
            )
        conn.commit()
        pytest.fail("Expected IntegrityError for FK violation was not raised")
    except pymysql.err.IntegrityError:
        conn.rollback()
    finally:
        conn.close()


def test_crawl_jobs_fk_enforced():
    """
    Input: None
    Output: None
    Details:
        Attempts to insert a crawl_jobs row referencing a nonexistent target_id.
        Expects pymysql.err.IntegrityError, confirming the FK is enforced.
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO crawl_jobs (task_id, target_id, status) VALUES (%s, %s, %s)",
                ("fk-test-task-99999", 999999, "queued"),
            )
        conn.commit()
        pytest.fail("Expected IntegrityError for FK violation was not raised")
    except pymysql.err.IntegrityError:
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    pass
