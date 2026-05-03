"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Nutch REST API client. Used by Celery workers to trigger crawl jobs
    and retrieve crawled content. TLS verification is controlled per-target
    via the tls_verify flag on the CrawlerTarget model.

    REST base URL: http://{NUTCH_HOST}:{NUTCH_PORT}
    Default port:  8081 (NutchServer default)

    Crawl pipeline:
        seed/create → INJECT → GENERATE → FETCH → PARSE → UPDATEDB
"""
# Imports
import logging
import os
import time
import uuid
import requests

# Module logger — defined before Globals so it is available everywhere below
logger = logging.getLogger(__name__)

# Globals
NUTCH_HOST = os.environ.get("NUTCH_HOST", "localhost")
NUTCH_PORT = int(os.environ.get("NUTCH_PORT", 8081))

_PIPELINE = ["INJECT", "GENERATE", "FETCH", "UPDATEDB"]
_TERMINAL_STATES = {"FINISHED", "FAILED", "KILLED"}

# job_type → extra args included in the job create body
_JOB_ARGS = {
    "INJECT":   {"depth": 1},
    "GENERATE": {},
    "FETCH":    {},
    "UPDATEDB": {},
}

# Functions
def get_session():
    """
    Input: None
    Output: requests.Session
    Details:
        Returns a new Session with SSL verification controlled by the
        INTERNAL_TLS_VERIFY environment variable (default: True).
        Injectable in tests via the session parameter on trigger_crawl / fetch_results.
    """
    session = requests.Session()
    verify = os.environ.get("INTERNAL_TLS_VERIFY", "true").lower() != "false"
    session.verify = verify
    return session


def _base_url():
    """
    Input: None
    Output: str — base URL for the Nutch REST API
    Details:
        Reads NUTCH_HOST and NUTCH_PORT from the module globals (set from env
        at import time).
    """
    return f"http://{NUTCH_HOST}:{NUTCH_PORT}"


def _wait_for_job(session, base_url, crawl_id, job_id, poll_interval=2, timeout=300):
    """
    Input:  session: requests.Session
            base_url: str
            crawl_id: str
            job_id: str
            poll_interval: int — seconds between polls
            timeout: int — max seconds to wait
    Output: str — terminal state ("FINISHED", "FAILED", or "KILLED")
    Details:
        Polls GET /job/{job_id}?crawlId= until the job reaches a terminal
        state or the timeout expires. Raises TimeoutError on timeout.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = session.get(
            f"{base_url}/job/{job_id}", params={"crawlId": crawl_id}
        )
        resp.raise_for_status()
        state = resp.json().get("state", "")
        if state in _TERMINAL_STATES:
            return state
        time.sleep(poll_interval)
    raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")


def trigger_crawl(seed_urls, crawl_id=None, tls_verify=True, session=None):
    """
    Input:  seed_urls: list[str] — seed URLs to crawl
            crawl_id: str|None — identifier reused across pipeline steps; generated if None
            tls_verify: bool — TLS verification for Nutch API requests (not the crawl targets)
            session: requests.Session|None — injectable for tests
    Output: str — crawl_id used for this crawl
    Details:
        Runs the full pipeline: seed/create → INJECT → GENERATE → FETCH →
        PARSE → UPDATEDB. Each step blocks until the job reaches a terminal
        state. Raises RuntimeError if any step ends in FAILED or KILLED.
    """
    if session is None:
        session = get_session()
    if crawl_id is None:
        crawl_id = str(uuid.uuid4())[:8]

    base = _base_url()

    # When TLS verification is disabled for this target, override the config
    # property on the server before submitting any jobs. The property is
    # already false by default in Nutch 1.23, but this makes the intent explicit
    # and handles cases where an operator has re-enabled checking globally.
    if not tls_verify:
        tls_resp = session.put(
            f"{base}/config/default/http.tls.certificates.check",
            data="false",
            headers={"Content-Type": "text/plain"},
        )
        tls_resp.raise_for_status()

    # Create seed file; response body is the seed directory path (plain text)
    seed_resp = session.post(
        f"{base}/seed/create",
        json={
            "name": crawl_id,
            "seedUrls": [{"url": u} for u in seed_urls],
        },
    )
    seed_resp.raise_for_status()
    seed_path = seed_resp.text.strip()

    # Run pipeline steps in order
    for job_type in _PIPELINE:
        args = dict(_JOB_ARGS[job_type])
        if job_type == "INJECT":
            # Nutch REST API reads args["url_dir"] in InjectJob.java
            args["url_dir"] = seed_path

        job_resp = session.post(
            f"{base}/job/create",
            json={
                "crawlId": crawl_id,
                "type": job_type,
                "confId": "default",
                "args": args,
            },
        )
        job_resp.raise_for_status()
        job_id = job_resp.json().get("id")
        state = _wait_for_job(session, base, crawl_id, job_id)
        if state != "FINISHED":
            raise RuntimeError(
                f"Nutch {job_type} job {job_id} ended in state {state}"
            )

    return crawl_id


def fetch_results(crawl_id, page_size=500, session=None):
    """
    Input:  crawl_id: str — crawl identifier (used for crawldb stats query)
            page_size: int — max nodes to retrieve from the in-memory fetchdb
            session: requests.Session|None — injectable for tests
    Output: dict with keys:
                "nodes"  — list of fetched URL records from GET /db/fetchdb
                           each record: {url, status, num_outlinks, outlinks: [{url, anchor}]}
                "stats"  — crawl DB statistics dict from POST /db/crawldb?type=stats
    Details:
        Calls two endpoints:
        1. GET /db/fetchdb?from=0&to=<page_size>
           Returns in-memory fetch results populated during the most recent crawl
           session on this server instance. Contains url, HTTP status, and outlink
           graph. Does NOT contain page text (text lives in Nutch segments on disk).
        2. POST /db/crawldb with type=stats and crawlId=<crawl_id>
           Returns aggregate counts (total URLs, per-status breakdown).
        Raises requests.HTTPError on non-2xx responses.
    """
    if session is None:
        session = get_session()

    base = _base_url()

    nodes_resp = session.get(
        f"{base}/db/fetchdb", params={"from": 0, "to": page_size}
    )
    nodes_resp.raise_for_status()
    raw_nodes = nodes_resp.json() or []

    normalized = [
        {
            "url": node.get("url"),
            "status": node.get("status"),
            "num_outlinks": node.get("numOfOutlinks", 0),
            "outlinks": [
                {"url": c.get("childUrl"), "anchor": c.get("anchorText")}
                for c in (node.get("children") or [])
            ],
        }
        for node in raw_nodes
    ]

    stats_resp = session.post(
        f"{base}/db/crawldb",
        json={"crawlId": crawl_id, "type": "stats", "confId": "default", "args": {}},
    )
    stats_resp.raise_for_status()
    stats = stats_resp.json() or {}

    return {"nodes": normalized, "stats": stats}


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
        tags. Script, style, and nav blocks are excluded. Falls back to the URL
        string on any error (network, timeout, encoding) so callers always
        receive a non-empty string to index.
    """
    from html.parser import HTMLParser

    class _TextExtractor(HTMLParser):
        """Minimal tag-stripping HTMLParser that skips scripts and styles."""
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

    try:
        resp = requests.get(url, timeout=timeout, verify=tls_verify)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "html" not in content_type and "xml" not in content_type:
            return url
        extractor = _TextExtractor()
        extractor.feed(resp.text)
        text = extractor.get_text()
        return text if text.strip() else url
    except Exception:
        logger.warning("_fetch_page_text failed for %s — indexing URL only", url, exc_info=True)
        return url


def _discover_urls(seed_url, tls_verify=True, max_depth=2, max_urls=500, timeout=10):
    """
    Input:
        seed_url  - str, starting URL
        tls_verify - bool, SSL verification
        max_depth  - int, how many link-hops to follow (0 = seed page only)
        max_urls   - int, cap on total URLs returned
        timeout    - int, per-request timeout in seconds
    Output:
        list[str] — discovered URLs in BFS order, seed first
    Details:
        BFS from seed_url staying on the same host. Follows redirects
        transparently (the final URL after redirect is recorded). Links are
        only extracted from HTML responses; CSS/JS/images are recorded but
        not followed. Fragment identifiers and off-host hrefs are ignored.
        Falls back to [seed_url] on any network error fetching the seed.
    """
    from html.parser import HTMLParser
    import urllib.parse

    class _LinkExtractor(HTMLParser):
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

    parsed_seed = urllib.parse.urlparse(seed_url)
    base_host = parsed_seed.netloc

    visited = set()
    queue = [(seed_url, 0)]
    result = []

    while queue and len(result) < max_urls:
        url, depth = queue.pop(0)
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
        result.append(final_url)

        if depth < max_depth and "html" in resp.headers.get("Content-Type", ""):
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
        Placeholder entry point. Call trigger_crawl() directly from Celery tasks.
    """
    pass


if __name__ == "__main__":
    main()
