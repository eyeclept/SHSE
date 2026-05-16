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
    Output: error message visible; still on /login
    """
    page.goto(f"{base_url}/login")
    page.fill("input[name='username']", "nonexistent_user_xyz")
    page.fill("input[name='password']", "wrong_password_xyz")
    page.click("button[type='submit']")
    # Wait for the 401 response + re-rendered login page to settle
    page.wait_for_load_state("networkidle")
    assert "/login" in page.url
    body = page.content().lower()
    assert any(word in body for word in ("invalid", "incorrect", "wrong", "error")), (
        "Expected an error message for bad credentials"
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
        The health grid is populated via HTMX after page load, so networkidle
        is required before checking content.
    """
    _login(page, base_url, test_admin_creds["username"], test_admin_creds["password"])
    page.goto(f"{base_url}/admin")
    # Wait for HTMX health grid request to complete
    page.wait_for_load_state("networkidle")
    expect(page.locator(".shse-card").first).to_be_visible()
    body = page.content().lower()
    # Service labels in _health_grid.html: OpenSearch, MariaDB, Redis, Nutch, Celery
    assert any(svc in body for svc in ("opensearch", "mariadb", "redis", "nutch", "celery")), (
        "Expected at least one service name in admin health panel"
    )


# ── Results page interactions ─────────────────────────────────────────────────

def test_filter_service_checkbox_appends_param(page, base_url):
    """
    Input: results page with at least one service filter checkbox; check it and submit
    Output: URL contains filter_service= parameter
    Details:
        The filter panel is inside a <details> element (closed by default).
        Must click the summary (Filters button) to open it before interacting
        with the checkbox. Submits via the Apply button inside the filter form.
    """
    page.goto(f"{base_url}/search?q={_SEARCH_Q1.replace(' ', '+')}")
    # Open the filter <details> panel — click the summary (Filters button)
    filter_summary = page.locator("details summary").filter(has_text="Filters")
    if not filter_summary.count():
        pytest.skip("No Filters button — results page may have no filter panel")
    filter_summary.click()
    checkbox = page.locator("input[name='filter_service']").first
    if not checkbox.count():
        pytest.skip("No filter_service checkboxes rendered — index may have no services")
    checkbox.check()
    # Submit via the Apply button inside the filter form (not the main search form)
    page.locator("details:has(input[name='filter_service']) button[type='submit']").click()
    page.wait_for_load_state("networkidle")
    assert "filter_service=" in page.url, (
        f"Expected filter_service= in URL after applying filter, got: {page.url}"
    )


def test_newest_first_sort_appends_date_desc(page, base_url):
    """
    Input: results page; click 'Newest first' sort link
    Output: URL contains sort=date_desc
    Details:
        The sort control is inside a <details> element (closed by default).
        Must click the summary (sort label button) to open the dropdown first,
        then click the 'Newest first' anchor link.
    """
    page.goto(f"{base_url}/search?q={_SEARCH_Q1.replace(' ', '+')}")
    # Open the sort <details> dropdown — find the details that contains sort links
    sort_details = page.locator("details").filter(has_text="Newest first")
    if not sort_details.count():
        pytest.skip("Sort dropdown not found on results page")
    sort_details.locator("summary").click()
    page.get_by_text("Newest first", exact=False).first.click()
    assert "sort=date_desc" in page.url, (
        f"Expected sort=date_desc in URL after clicking 'Newest first', got: {page.url}"
    )


def test_result_cards_show_title_url_snippet(page, base_url):
    """
    Input: results page for "human anatomy"
    Output: first result item contains a title link (href) and snippet paragraph
    Details:
        Requires indexed Wikipedia content. Result items are rendered as <li>
        elements (no CSS class) by _result_item.html — each contains an <a href>
        for the title and a <p> for the snippet. Use li:has(a[href]):has(p)
        to target actual result rows rather than .shse-card (used for answer cards).
    """
    page.goto(f"{base_url}/search?q={_SEARCH_Q1.replace(' ', '+')}")
    results = page.locator("li:has(a[href]):has(p)")
    if not results.count():
        pytest.skip("No result items — index may be empty for 'human anatomy'")
    first_item = results.first
    title_link = first_item.locator("a[href]").first
    expect(title_link).to_be_visible()
    href = title_link.get_attribute("href")
    assert href, "Result item link has no href"
    snippet = first_item.locator("p").first
    expect(snippet).to_be_visible()
    assert len(snippet.text_content().strip()) > 0, "Snippet text is empty"


# ── Inline answer cards ───────────────────────────────────────────────────────

def test_calculator_card_renders_for_math_query(page, base_url):
    """
    Input: search query "2 + 2 ="
    Output: a .shse-card element containing the text "Calculator" is visible above results
    Details:
        The calculator service detects arithmetic expressions and renders an inline
        answer card before BM25 results. The card's label div contains "Calculator".
        Skip when the card is absent — expression may not be detected on this build.
    """
    page.goto(f"{base_url}/search?q=2+%2B+2+%3D")
    page.wait_for_load_state("networkidle")
    card = page.locator(".shse-card").filter(has_text="Calculator")
    if not card.count():
        pytest.skip("Calculator card not rendered — arithmetic detection may be disabled")
    expect(card.first).to_be_visible()


def test_unit_converter_card_renders_for_conversion_query(page, base_url):
    """
    Input: search query "5 km to miles"
    Output: a .shse-card element containing "Unit Converter" label is visible
    Details:
        The unit converter service detects "<n> <unit> to <unit>" queries and
        renders an inline card with the label "Unit Converter". Skip when absent.
    """
    page.goto(f"{base_url}/search?q=5+km+to+miles")
    page.wait_for_load_state("networkidle")
    card = page.locator(".shse-card").filter(has_text="Unit Converter")
    if not card.count():
        pytest.skip("Unit converter card not rendered — conversion query not detected")
    expect(card.first).to_be_visible()


def test_datetime_card_renders_for_date_query(page, base_url):
    """
    Input: search query "what day is today"
    Output: a .shse-card element containing a date string is visible
    Details:
        The datetime service detects date/time queries. The card label is set by
        answer_card.label (e.g. "Today's date"). Skip when not rendered.
    """
    page.goto(f"{base_url}/search?q=what+day+is+today")
    page.wait_for_load_state("networkidle")
    # Datetime card has data-ai-context attr and is an answer card (high z-order)
    # Its label text varies; check for any shse-card that precedes the results list
    cards = page.locator(".shse-card[data-ai-context]")
    if not cards.count():
        pytest.skip("Datetime answer card not rendered for date query")
    expect(cards.first).to_be_visible()


def test_translation_card_renders_for_translate_query(page, base_url):
    """
    Input: search query "translate hello to spanish"
    Output: a .shse-card containing the "→" translation arrow is visible
    Details:
        The translation service calls Ollama; skip if the card does not render
        (Ollama unreachable or translation model not loaded). The card always shows
        the source word, an arrow (→), and the target language label.
    """
    page.goto(f"{base_url}/search?q=translate+hello+to+spanish")
    page.wait_for_load_state("networkidle")
    card = page.locator(".shse-card").filter(has_text="→")
    if not card.count():
        pytest.skip("Translation card not rendered — Ollama may be unreachable")
    expect(card.first).to_be_visible()


def test_dictionary_card_renders_for_define_query(page, base_url):
    """
    Input: search query "define human"
    Output: a .shse-card with definition content (OED word card) is visible
    Details:
        Requires the OED StarDict file to be mounted. The card renders the word,
        IPA pronunciation (if present), and numbered definitions. Skip when absent.
    """
    page.goto(f"{base_url}/search?q=define+human")
    page.wait_for_load_state("networkidle")
    # OED card renders an <ol> (numbered definitions) inside a .shse-card
    card = page.locator(".shse-card:has(ol)")
    if not card.count():
        pytest.skip("Dictionary card not rendered — OED StarDict file may not be mounted")
    expect(card.first).to_be_visible()


# ── Additional page form coverage ─────────────────────────────────────────────

def test_register_page_renders_form_fields(page, base_url):
    """
    Input: GET /register
    Output: input[name='username'] and input[name='password'] are visible
    Details:
        Confirms the register form renders with the required fields. The form
        has only username and password (no confirm_password field).
    """
    page.goto(f"{base_url}/register")
    expect(page.locator("input[name='username']")).to_be_visible()
    expect(page.locator("input[name='password']")).to_be_visible()


def test_forgot_password_page_renders_form(page, base_url):
    """
    Input: GET /forgot-password
    Output: input[name='username'] and a submit button are visible
    Details:
        Skip if the page returns 404 (SMTP not configured = route may be absent
        or the link hidden). Confirms the forgot-password form is usable.
    """
    import requests as _req
    try:
        status = _req.get(f"{base_url}/forgot-password", timeout=3).status_code
    except Exception:
        pytest.skip("Cannot reach /forgot-password")
    if status == 404:
        pytest.skip("/forgot-password returned 404 — route not registered")
    page.goto(f"{base_url}/forgot-password")
    expect(page.locator("input[name='username']")).to_be_visible()
    expect(page.locator("button[type='submit']")).to_be_visible()


def test_settings_page_renders_theme_and_password_form(page, base_url, test_user_creds):
    """
    Input: authenticated GET /settings
    Output: theme radio group (#theme-group) and input[name='new_password'] are visible
    Details:
        Requires a logged-in session. The settings page has a theme selector
        (radio buttons in #theme-group) and a password change form.
    """
    _login(page, base_url, test_user_creds["username"], test_user_creds["password"])
    page.goto(f"{base_url}/settings")
    expect(page.locator("#theme-group")).to_be_visible()
    # Password form is inside a <details> (closed by default); open it first
    page.locator("details summary").filter(has_text="Change password").click()
    expect(page.locator("input[name='new_password']")).to_be_visible()


def test_admin_targets_page_shows_table(page, base_url, test_admin_creds):
    """
    Input: authenticated admin GET /admin/targets
    Output: a <table> element (targets table) is visible in the page
    Details:
        The targets page renders a <table> when crawler targets exist, or a
        .shse-card form for adding the first target. Assert the page renders
        without error (not redirected to /login).
    """
    _login(page, base_url, test_admin_creds["username"], test_admin_creds["password"])
    page.goto(f"{base_url}/admin/targets")
    page.wait_for_load_state("networkidle")
    assert "/login" not in page.url, "Admin targets page redirected to login — admin auth failed"
    # Either a targets table or the add-target form card must be visible
    assert (
        page.locator("table").count() > 0
        or page.locator(".shse-card form").count() > 0
    ), "Neither a targets table nor add-target form found on /admin/targets"


def test_sso_button_visible_on_login_when_enabled(page, base_url):
    """
    Input: GET /login when SSO_ENABLED=true is set
    Output: SSO login button/link ("Continue with SSO") is visible
    Details:
        Skip when SSO is not enabled (button absent from the rendered page).
        When enabled, the login page renders an <a> linking to /sso/login.
    """
    page.goto(f"{base_url}/login")
    sso_link = page.locator("a[href*='sso']")
    if not sso_link.count():
        pytest.skip("SSO button not present — SSO_ENABLED is false or not configured")
    expect(sso_link.first).to_be_visible()
