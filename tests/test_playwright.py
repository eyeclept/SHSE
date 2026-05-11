"""
Author: Richard Baldwin
Date:   2026
Email:  eyeclept@pm.me

Description:
    Playwright end-to-end integration tests for the SHSE web UI.
    Requires the full Docker Compose stack to be running:
        docker compose up -d   (then ./rebuild.sh if flask_app/ changed)

    All tests are skipped automatically when the Flask server is not reachable
    at http://localhost:5000.

    Search queries use "human anatomy" and "cell biology" which return results
    from the default Kiwix Wikipedia crawl target.

    Prerequisites:
        pip install pytest-playwright
        playwright install chromium
"""
# Imports
import logging
import re

import pytest
import requests
from playwright.sync_api import expect

# Globals
logger = logging.getLogger(__name__)

_BASE_URL = "http://localhost:5000"
_SEARCH_Q1 = "human anatomy"
_SEARCH_Q2 = "cell biology"


# Functions
def _stack_up():
    """
    Input: None
    Output: bool — True if Flask server responds at localhost:5000
    """
    try:
        requests.get(_BASE_URL, timeout=3)
        return True
    except Exception:
        logger.warning("Flask stack not reachable — skipping Playwright tests")
        return False


pytestmark = pytest.mark.skipif(
    not _stack_up(),
    reason="Flask stack not running — start with: docker compose up -d",
)


def _login(page, base_url, username, password):
    """
    Input: page, base_url, username, password
    Output: None — navigates to /login, fills credentials, submits form
    """
    page.goto(f"{base_url}/login")
    page.fill("input[name='username']", username)
    page.fill("input[name='password']", password)
    page.click("button[type='submit']")


# ── Unauthenticated UI ────────────────────────────────────────────────────────

def test_home_page_loads_with_search_input(page, base_url):
    """
    Input: GET /
    Output: 200; search input[name='q'] is visible
    Details:
        Confirms the home page renders without error and exposes the
        primary search field that all queries go through.
    """
    page.goto(f"{base_url}/")
    expect(page.locator("input[name='q']")).to_be_visible()


def test_non_empty_query_navigates_to_results(page, base_url):
    """
    Input: submit "human anatomy" from the home page search form
    Output: URL contains /search?q=; at least one .shse-card result card visible
    Details:
        Requires the Kiwix Wikipedia crawl to have completed so there are
        indexed documents matching "human anatomy".
    """
    page.goto(f"{base_url}/")
    page.fill("input[name='q']", _SEARCH_Q1)
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"/search\?q="))
    expect(page.locator(".shse-card").first).to_be_visible()


def test_empty_query_does_not_500(page, base_url):
    """
    Input: submit empty query from home page
    Output: page does not show a 500 error; no "Internal Server Error" text
    Details:
        The results route treats an empty q as a valid no-op; it should
        render an empty-state page rather than raising an exception.
    """
    page.goto(f"{base_url}/search?q=")
    assert "Internal Server Error" not in page.content()
    assert page.url.endswith("/search?q=") or "/search" in page.url


def test_login_page_shows_credential_fields(page, base_url):
    """
    Input: GET /login
    Output: input[name='username'] and input[name='password'] are visible
    """
    page.goto(f"{base_url}/login")
    expect(page.locator("input[name='username']")).to_be_visible()
    expect(page.locator("input[name='password']")).to_be_visible()


def test_valid_credentials_redirect_to_home(page, base_url, test_user_creds):
    """
    Input: POST /login with correct username and password
    Output: redirected to /; session cookie is present in browser context
    """
    _login(page, base_url, test_user_creds["username"], test_user_creds["password"])
    assert "/" in page.url and "/login" not in page.url
    cookies = {c["name"]: c for c in page.context.cookies()}
    assert "session" in cookies, "session cookie missing after successful login"


def test_invalid_credentials_show_error(page, base_url):
    """
    Input: POST /login with wrong password
    Output: error message visible; still on /login; no session cookie set
    """
    page.goto(f"{base_url}/login")
    page.fill("input[name='username']", "nonexistent_user_xyz")
    page.fill("input[name='password']", "wrong_password_xyz")
    page.click("button[type='submit']")
    assert "/login" in page.url
    body = page.content().lower()
    assert any(word in body for word in ("invalid", "incorrect", "wrong", "error")), (
        "Expected an error message for bad credentials"
    )
    cookies = {c["name"]: c for c in page.context.cookies()}
    session = cookies.get("session")
    assert session is None or not session.get("value"), (
        "session cookie should not be set after failed login"
    )


# ── Authenticated UI ──────────────────────────────────────────────────────────

def test_logout_redirects_to_login(page, base_url, test_user_creds):
    """
    Input: logged-in session; GET /logout
    Output: redirected to /login
    """
    _login(page, base_url, test_user_creds["username"], test_user_creds["password"])
    page.goto(f"{base_url}/logout")
    expect(page).to_have_url(re.compile(r"/login"))


def test_unauthenticated_history_redirects_to_login(page, base_url):
    """
    Input: GET /history without a session
    Output: redirected to /login
    """
    page.goto(f"{base_url}/history")
    expect(page).to_have_url(re.compile(r"/login"))


def test_history_lists_two_recent_queries(page, base_url, test_user_creds):
    """
    Input: two searches performed while logged in
    Output: /history page shows both query strings
    Details:
        Performs two distinct searches then verifies both appear in the
        history list. Requires login so queries are attributed to the user.
    """
    _login(page, base_url, test_user_creds["username"], test_user_creds["password"])
    page.goto(f"{base_url}/search?q={_SEARCH_Q1.replace(' ', '+')}")
    page.goto(f"{base_url}/search?q={_SEARCH_Q2.replace(' ', '+')}")
    page.goto(f"{base_url}/history")
    body = page.content()
    assert _SEARCH_Q1 in body, f"Query '{_SEARCH_Q1}' not in history"
    assert _SEARCH_Q2 in body, f"Query '{_SEARCH_Q2}' not in history"


def test_non_admin_cannot_access_admin_panel(page, base_url, test_user_creds):
    """
    Input: GET /admin as a logged-in non-admin user
    Output: not 200 with admin content (redirect to /login or /; or 403)
    """
    _login(page, base_url, test_user_creds["username"], test_user_creds["password"])
    page.goto(f"{base_url}/admin", wait_until="load")
    assert "/admin" not in page.url or "Forbidden" in page.content(), (
        "Non-admin user should not see /admin page content"
    )


def test_admin_user_sees_health_panel(page, base_url, test_admin_creds):
    """
    Input: GET /admin as admin user
    Output: health-check panel visible (shse-card elements with service status)
    Details:
        Confirms the admin health grid renders for an authenticated admin.
        Checks for the shse-card class used by _health_grid.html partial.
    """
    _login(page, base_url, test_admin_creds["username"], test_admin_creds["password"])
    page.goto(f"{base_url}/admin")
    expect(page.locator(".shse-card").first).to_be_visible()
    body = page.content().lower()
    assert any(svc in body for svc in ("opensearch", "mariadb", "redis", "flask")), (
        "Expected at least one service name in admin health panel"
    )


# ── Results page interactions ─────────────────────────────────────────────────

def test_filter_service_checkbox_appends_param(page, base_url):
    """
    Input: results page with at least one service filter checkbox; check it and submit
    Output: URL contains filter_service= parameter
    Details:
        Requires at least one indexed service (kiwix-wikipedia) for the
        checkbox to appear. Checks the box, then submits via the search form.
    """
    page.goto(f"{base_url}/search?q={_SEARCH_Q1.replace(' ', '+')}")
    checkbox = page.locator("input[name='filter_service']").first
    if not checkbox.count():
        pytest.skip("No filter_service checkboxes rendered — index may have no services")
    checkbox.check()
    page.locator("input[name='q']").press("Enter")
    assert "filter_service=" in page.url, (
        f"Expected filter_service= in URL after checking filter, got: {page.url}"
    )


def test_newest_first_sort_appends_date_desc(page, base_url):
    """
    Input: results page; click 'Newest first' sort link
    Output: URL contains sort=date_desc
    Details:
        The sort control uses anchor links — clicking 'Newest first' navigates
        to the same query with sort=date_desc appended.
    """
    page.goto(f"{base_url}/search?q={_SEARCH_Q1.replace(' ', '+')}")
    page.get_by_text("Newest first", exact=False).first.click()
    assert "sort=date_desc" in page.url, (
        f"Expected sort=date_desc in URL after clicking 'Newest first', got: {page.url}"
    )


def test_result_cards_show_title_url_snippet(page, base_url):
    """
    Input: results page for "human anatomy"
    Output: first result card contains title text, a URL, and snippet text
    Details:
        Requires indexed Wikipedia content. Checks the _result_item.html
        structure: anchor with title text, href URL, and paragraph snippet.
    """
    page.goto(f"{base_url}/search?q={_SEARCH_Q1.replace(' ', '+')}")
    cards = page.locator(".shse-card")
    if not cards.count():
        pytest.skip("No result cards — index may be empty for 'human anatomy'")
    first_card = cards.first
    title_link = first_card.locator("a[href]").first
    expect(title_link).to_be_visible()
    href = title_link.get_attribute("href")
    assert href, "Result card link has no href"
    snippet = first_card.locator("p").first
    expect(snippet).to_be_visible()
    assert len(snippet.text_content()) > 0, "Snippet text is empty"
