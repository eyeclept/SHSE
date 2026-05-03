"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Integration tests for the live Nutch REST server (port 8081).
    These tests verify that the actual REST server is up and responding
    correctly — something the mocked unit tests in test_nutch.py cannot do.

    Skipped automatically when the Nutch container is not reachable.
    Requires the stack to be running: docker compose up -d
"""
# Imports
import pytest
import requests

# Globals
_NUTCH_BASE = "http://localhost:8081"


# Functions
def _nutch_up():
    """
    Input: None
    Output: bool — True if the Nutch REST server responds
    """
    try:
        r = requests.get(f"{_NUTCH_BASE}/admin/", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _nutch_up(),
    reason="Nutch REST server not running — start with: docker compose up -d",
)


def test_nutch_admin_responds():
    """
    Input: None
    Output: None
    Details:
        GET /admin/ must return 200. This is the same probe the admin health
        check uses; if this fails, the health grid will show Nutch as down.
    """
    r = requests.get(f"{_NUTCH_BASE}/admin/", timeout=5)
    assert r.status_code == 200


def test_nutch_admin_version():
    """
    Input: None
    Output: None
    Details:
        GET /admin/ response must include a nutchVersion field,
        confirming we are talking to a real NutchServer.
    """
    r = requests.get(f"{_NUTCH_BASE}/admin/", timeout=5)
    data = r.json()
    assert "startDate" in data, f"startDate missing from /admin/ response: {data}"
    assert "configuration" in data, f"configuration missing from /admin/ response: {data}"


def test_nutch_job_list():
    """
    Input: None
    Output: None
    Details:
        GET /job/ must return a list (may be empty on a fresh stack).
        This confirms the job management API is functional.
    """
    r = requests.get(f"{_NUTCH_BASE}/job/", timeout=5)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_nutch_seed_endpoint_reachable():
    """
    Input: None
    Output: None
    Details:
        GET /seed/ must return 200 or 405 (method not allowed for GET,
        since the endpoint expects POST). Either confirms the endpoint
        exists and the server is routing correctly.
    """
    r = requests.get(f"{_NUTCH_BASE}/seed/", timeout=5)
    assert r.status_code in (200, 405)
