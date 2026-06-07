"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Unit tests for flask_app/services/nutch.py.
    All tests use a mock requests.Session; no live Nutch container required.
"""
# Imports
from unittest.mock import MagicMock, patch


# Functions
def test_fetch_page_text_returns_stripped_text():
    """
    Input: mock HTTP response returning HTML
    Output: visible text with tags stripped, scripts excluded
    """
    from flask_app.services.nutch import _fetch_page_text

    html = ("<html><head><title>Test</title></head><body>"
            "<script>var x = 1;</script><nav>Menu</nav>"
            "<h1>Hello World</h1><p>This is a paragraph.</p>"
            "</body></html>")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.headers = {"Content-Type": "text/html"}
    mock_resp.text = html

    with patch("flask_app.services.nutch.requests.get", return_value=mock_resp):
        text = _fetch_page_text("http://example.com/page")

    assert "Hello World" in text
    assert "This is a paragraph" in text
    assert "var x = 1" not in text
    assert "<" not in text


def test_fetch_page_text_falls_back_to_url_on_error():
    """
    Input: network error when fetching page
    Output: returns the URL string
    """
    from flask_app.services.nutch import _fetch_page_text

    with patch("flask_app.services.nutch.requests.get", side_effect=ConnectionError("refused")):
        result = _fetch_page_text("http://example.com/page")

    assert result == "http://example.com/page"


def test_discover_urls_with_text_fetches_each_page_once():
    """
    Input: seed page linking to one same-host page; _discover_urls(with_text=True)
    Output: [(url, text), ...] with text from the SAME fetch — each page is
            requested exactly once (no second GET to extract text)
    Details:
        Regression test for efficiency finding #3 (every discovered URL was
        fetched twice: once in discovery for links, once again for text).
    """
    from flask_app.services import nutch

    seed = "http://site.local/"
    page2 = "http://site.local/page2"
    bodies = {
        seed: '<html><body><h1>Home</h1><a href="/page2">next</a></body></html>',
        page2: "<html><body><p>Second page body.</p></body></html>",
    }
    calls = []

    def fake_get(url, **_kw):
        calls.append(url)
        r = MagicMock()
        r.raise_for_status.return_value = None
        r.headers = {"Content-Type": "text/html"}
        r.text = bodies[url]
        r.url = url
        return r

    with patch("flask_app.services.nutch.requests.get", side_effect=fake_get):
        pages = nutch._discover_urls(seed, max_depth=1, with_text=True)

    assert [u for u, _ in pages] == [seed, page2]
    text_map = dict(pages)
    assert "Home" in text_map[seed]
    assert "Second page body" in text_map[page2]
    # Each page fetched exactly once — the double-fetch is gone.
    assert calls == [seed, page2]
