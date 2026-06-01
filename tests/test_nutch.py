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
