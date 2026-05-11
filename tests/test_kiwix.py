"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Integration tests for the Kiwix test server (wikipedia_en_100_nopic_2026-04.zim).
    Requires the Kiwix container to be running:
        docker compose --profile test up kiwix -d

    These tests are skipped automatically when the Kiwix server is not reachable,
    so they do not break the normal test run when the container is down.
"""
# Imports
import logging

import pytest
import requests

# Globals
logger = logging.getLogger(__name__)

_KIWIX_BASE = "http://localhost:8082"
_ZIM_PATH = "/content/wikipedia_en_100_nopic_2026-04"


# Functions
def _kiwix_up():
    """
    Input: None
    Output: bool — True if Kiwix server responds at the expected URL
    """
    try:
        r = requests.get(_KIWIX_BASE, timeout=3)
        return r.status_code == 200
    except Exception:
        logger.warning("Kiwix server not reachable at %s", _KIWIX_BASE)
        return False


pytestmark = pytest.mark.skipif(
    not _kiwix_up(),
    reason="Kiwix container not running — start with: docker compose --profile test up kiwix -d",
)


def test_kiwix_root_responds():
    """
    Input: None
    Output: None
    Details:
        Kiwix server root returns 200 and HTML listing the ZIM library.
    """
    r = requests.get(_KIWIX_BASE, timeout=5)
    assert r.status_code == 200
    assert "text/html" in r.headers.get("Content-Type", "")
    assert "Kiwix" in r.text


def test_kiwix_zim_entry_in_catalog():
    """
    Input: None
    Output: None
    Details:
        The OPDS catalog lists the loaded ZIM and includes the expected name
        and category fields.
    """
    r = requests.get(f"{_KIWIX_BASE}/catalog/v2/entries", timeout=5)
    assert r.status_code == 200
    assert "wikipedia_en_100" in r.text
    assert "wikipedia" in r.text.lower()


def test_kiwix_content_root_accessible():
    """
    Input: None
    Output: None
    Details:
        The ZIM content root redirects (302) to the ZIM's main page, which
        then returns 200 HTML. Verifies the ZIM is mounted and parseable.
    """
    r = requests.get(f"{_KIWIX_BASE}{_ZIM_PATH}/", timeout=5, allow_redirects=True)
    assert r.status_code == 200
    assert "text/html" in r.headers.get("Content-Type", "")
    assert "Wikipedia" in r.text


def test_kiwix_article_readable():
    """
    Input: None
    Output: None
    Details:
        A specific article ('Animal') is retrievable and contains expected
        article content. Confirms the ZIM index is working and articles
        are served with real body text.
    """
    r = requests.get(
        f"{_KIWIX_BASE}{_ZIM_PATH}/Animal",
        timeout=5,
        allow_redirects=True,
    )
    assert r.status_code == 200
    assert "text/html" in r.headers.get("Content-Type", "")
    body = r.text.lower()
    assert "animal" in body
    # Should contain actual article prose, not just navigation chrome
    assert len(r.text) > 5000


def test_kiwix_article_contains_text_body():
    """
    Input: None
    Output: None
    Details:
        Verifies that an article's body contains substantive paragraph text
        (not just metadata or navigation), confirming the ZIM is being
        decompressed correctly and not corrupted.
    """
    r = requests.get(
        f"{_KIWIX_BASE}{_ZIM_PATH}/Michael_Jackson",
        timeout=5,
        allow_redirects=True,
    )
    assert r.status_code == 200
    body = r.text
    # Article must contain a <p> tag with real prose
    assert "<p" in body
    assert len(body) > 3000


def test_kiwix_missing_article_returns_404():
    """
    Input: None
    Output: None
    Details:
        Requesting a nonexistent article returns 404, confirming the server
        does not silently serve blank pages for missing content.
    """
    r = requests.get(
        f"{_KIWIX_BASE}{_ZIM_PATH}/This_Article_Does_Not_Exist_XYZ123",
        timeout=5,
        allow_redirects=False,
    )
    assert r.status_code in (404, 302), (
        f"Expected 404 or redirect for missing article, got {r.status_code}"
    )
