"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Web crawler utilities used by Celery workers. Provides BFS URL discovery
    and plain-text extraction from HTML pages.
"""
# Imports
import logging
import urllib.parse
from collections import deque
from html.parser import HTMLParser

import requests

# Module logger — defined before Globals so it is available everywhere below
logger = logging.getLogger(__name__)

# Globals

class _TextExtractor(HTMLParser):
    """Tag-stripping HTMLParser that skips scripts, styles, and nav blocks."""
    def __init__(self):
        super().__init__()
        self._parts = []
        self._skip = False
        self._skip_tags = {"script", "style", "nav", "header", "footer", "noscript"}

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip = True

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def get_text(self):
        return " ".join(self._parts)


class _LinkExtractor(HTMLParser):
    """HTMLParser that collects href values from anchor tags."""
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value and not value.startswith(
                    ("#", "javascript:", "mailto:", "data:")
                ):
                    self.links.append(value)

# Functions
def _extract_text(resp, fallback_url):
    """
    Input:
        resp         - requests.Response, already fetched with status checked
        fallback_url - str returned when the body has no extractable text
    Output:
        str — visible plain text, or fallback_url for non-markup/empty bodies
    Details:
        Tag-stripping extraction shared by _fetch_page_text and _discover_urls so
        a page fetched once during discovery does not need a second fetch just to
        extract its text. Only HTML/XML bodies are parsed; anything else returns
        the fallback URL.
    """
    content_type = resp.headers.get("Content-Type", "")
    if "html" not in content_type and "xml" not in content_type:
        return fallback_url
    extractor = _TextExtractor()
    extractor.feed(resp.text)
    text = extractor.get_text()
    return text if text.strip() else fallback_url


def _fetch_page_text(url, tls_verify=True, timeout=10):
    """
    Input:
        url        - str, fully-qualified URL to fetch
        tls_verify - bool, whether to verify TLS certificates
        timeout    - int, request timeout in seconds
    Output:
        str — visible plain text extracted from the HTML response body,
              or the URL itself when fetching or parsing fails
    Details:
        Uses requests.get() to fetch the page and stdlib html.parser to strip
        tags. Falls back to the URL string on any error (network, timeout,
        encoding) so callers always receive a non-empty string to index.
    """
    try:
        resp = requests.get(url, timeout=timeout, verify=tls_verify)
        resp.raise_for_status()
        return _extract_text(resp, url)
    except Exception:
        logger.warning("_fetch_page_text failed for %s — indexing URL only", url, exc_info=True)
        return url


def _discover_urls(seed_url, tls_verify=True, max_depth=2, max_urls=500, timeout=10, with_text=False):
    """
    Input:
        seed_url  - str, starting URL
        tls_verify - bool, SSL verification
        max_depth  - int, how many link-hops to follow (0 = seed page only)
        max_urls   - int, cap on total URLs returned
        timeout    - int, per-request timeout in seconds
        with_text  - bool, when True return (url, text) tuples carrying the text
                     extracted from the page already fetched during discovery,
                     so callers need not fetch each page a second time
    Output:
        list[str] when with_text is False (URLs in BFS order, seed first);
        list[(str, str)] of (url, extracted_text) when with_text is True
    Details:
        BFS from seed_url staying on the same host. Follows redirects
        transparently (the final URL after redirect is recorded). Links are
        only extracted from HTML responses; CSS/JS/images are recorded but
        not followed. Fragment identifiers and off-host hrefs are ignored.
        Falls back to [seed_url] on any network error fetching the seed.
    """
    parsed_seed = urllib.parse.urlparse(seed_url)
    base_host = parsed_seed.netloc

    visited = set()
    queue = deque([(seed_url, 0)])
    result = []

    while queue and len(result) < max_urls:
        url, depth = queue.popleft()
        norm = url.split("#")[0]
        if norm in visited:
            continue
        visited.add(norm)

        try:
            resp = requests.get(norm, timeout=timeout, verify=tls_verify, allow_redirects=True)
            resp.raise_for_status()
        except Exception:
            logger.warning("_discover_urls: skipping %s", norm, exc_info=True)
            continue

        final_url = resp.url.split("#")[0]
        if urllib.parse.urlparse(final_url).netloc != base_host:
            continue
        if final_url not in visited:
            visited.add(final_url)

        content_type = resp.headers.get("Content-Type", "")
        if with_text:
            # Reuse the response we just fetched to extract text — no second GET.
            result.append((final_url, _extract_text(resp, final_url)))
        else:
            result.append(final_url)

        if depth < max_depth and "html" in content_type:
            extractor = _LinkExtractor()
            extractor.feed(resp.text)
            for href in extractor.links:
                abs_url = urllib.parse.urljoin(final_url, href).split("#")[0]
                parsed = urllib.parse.urlparse(abs_url)
                if (
                    parsed.netloc == base_host
                    and parsed.scheme in ("http", "https")
                    and abs_url not in visited
                ):
                    queue.append((abs_url, depth + 1))

    return result


def main():
    """
    Input: None
    Output: None
    Details:
        Placeholder entry point.
    """
    pass


if __name__ == "__main__":
    main()
