"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Unit tests for flask_app/services/nutch.py.
    All tests use a mock requests.Session; no live Nutch container required.
"""
# Imports
import pytest
from unittest.mock import MagicMock, call, patch

from flask_app.services.nutch import trigger_crawl, fetch_results, _PIPELINE

# Globals
SEED_PATH = "seedFiles/seed-1234567890/urls"


# Functions
def _make_session(seed_path=SEED_PATH, job_states=None):
    """
    Input:  seed_path: str — value returned by POST /seed/create
            job_states: list[str]|None — terminal state per pipeline step;
                        defaults to FINISHED for every step
    Output: MagicMock requests.Session configured with canned responses
    Details:
        Wires session.post and session.get so that:
        - POST /seed/create returns seed_path as plain text
        - POST /job/create returns {"id": "<step>-job"} for each pipeline step
        - GET /job/{id} returns {"state": <state>} immediately (no polling needed)
    """
    if job_states is None:
        job_states = ["FINISHED"] * len(_PIPELINE)

    session = MagicMock()

    # POST responses: first call is seed/create, then one per pipeline step
    post_responses = []

    seed_resp = MagicMock()
    seed_resp.status_code = 200
    seed_resp.text = seed_path
    seed_resp.raise_for_status = MagicMock()
    post_responses.append(seed_resp)

    for i, step in enumerate(_PIPELINE):
        jr = MagicMock()
        jr.status_code = 200
        jr.json.return_value = {"id": f"{step.lower()}-job"}
        jr.raise_for_status = MagicMock()
        post_responses.append(jr)

    session.post.side_effect = post_responses

    # GET responses: one per pipeline step, returns terminal state immediately
    get_responses = []
    for step, state in zip(_PIPELINE, job_states):
        gr = MagicMock()
        gr.status_code = 200
        gr.json.return_value = {"id": f"{step.lower()}-job", "state": state}
        gr.raise_for_status = MagicMock()
        get_responses.append(gr)

    session.get.side_effect = get_responses

    return session


def test_trigger_crawl_returns_crawl_id():
    """
    Input: mock session with all steps FINISHED
    Output: crawl_id returned equals the one passed in
    Details:
        Verifies that trigger_crawl returns the provided crawl_id on success.
    """
    session = _make_session()
    result = trigger_crawl(["http://host1", "http://host2"], crawl_id="test-01", session=session)
    assert result == "test-01"


def test_trigger_crawl_seed_request_body():
    """
    Input: mock session, known seed URLs
    Output: first POST call body contains seedUrls with correct structure
    Details:
        Verifies the seed/create POST body format: name == crawl_id,
        seedUrls is a list of {url: ...} objects.
    """
    session = _make_session()
    seed_urls = ["http://svc1.local", "http://svc2.local"]
    trigger_crawl(seed_urls, crawl_id="cid-01", session=session)

    seed_call = session.post.call_args_list[0]
    body = seed_call.kwargs.get("json") or seed_call.args[1] if len(seed_call.args) > 1 else seed_call.kwargs["json"]
    assert body["name"] == "cid-01"
    assert body["seedUrls"] == [{"url": u} for u in seed_urls]


def test_trigger_crawl_runs_full_pipeline():
    """
    Input: mock session, all steps FINISHED
    Output: POST /job/create called once per pipeline step in order
    Details:
        Verifies that all five job types (INJECT, GENERATE, FETCH, PARSE, UPDATEDB)
        are submitted in the correct order.
    """
    session = _make_session()
    trigger_crawl(["http://host1"], crawl_id="cid-02", session=session)

    # post calls: index 0 = seed/create, indices 1-5 = job/create per step
    job_posts = session.post.call_args_list[1:]
    assert len(job_posts) == len(_PIPELINE)

    for i, step in enumerate(_PIPELINE):
        body = job_posts[i].kwargs.get("json") or job_posts[i].args[1]
        assert body["type"] == step
        assert body["crawlId"] == "cid-02"


def test_trigger_crawl_inject_includes_seed_dir():
    """
    Input: mock session returning a known seed path
    Output: INJECT job create body contains seedDir pointing to the seed path
    Details:
        Verifies that the seed path returned by /seed/create is forwarded to
        the INJECT job args as seedDir.
    """
    session = _make_session(seed_path="/some/seed/path")
    trigger_crawl(["http://host1"], crawl_id="cid-03", session=session)

    inject_call = session.post.call_args_list[1]
    body = inject_call.kwargs.get("json") or inject_call.args[1]
    assert body["type"] == "INJECT"
    assert body["args"]["seedDir"] == "/some/seed/path"


def test_trigger_crawl_raises_on_failed_job():
    """
    Input: mock session where FETCH step returns FAILED state
    Output: RuntimeError raised with FETCH in the message
    Details:
        Verifies that a FAILED job state stops the pipeline and surfaces
        the failure rather than silently continuing.
    """
    states = ["FINISHED", "FINISHED", "FAILED", "FINISHED", "FINISHED"]
    session = _make_session(job_states=states)

    with pytest.raises(RuntimeError, match="FETCH"):
        trigger_crawl(["http://host1"], crawl_id="cid-04", session=session)


def test_trigger_crawl_generates_crawl_id_when_none():
    """
    Input: no crawl_id provided
    Output: returned crawl_id is a non-empty string
    Details:
        Verifies that trigger_crawl generates a crawl_id when one is not supplied.
    """
    session = _make_session()
    result = trigger_crawl(["http://host1"], session=session)
    assert isinstance(result, str)
    assert len(result) > 0


def _make_session_with_tls(seed_path=SEED_PATH):
    """
    Input:  seed_path: str
    Output: MagicMock requests.Session pre-configured with a PUT response
    Details:
        Extends _make_session by prepending a PUT response for the TLS config
        endpoint, matching the call order when tls_verify=False is passed to
        trigger_crawl.
    """
    session = _make_session(seed_path=seed_path)

    put_resp = MagicMock()
    put_resp.status_code = 200
    put_resp.raise_for_status = MagicMock()
    session.put.return_value = put_resp

    return session


def test_tls_patch_sends_put_when_disabled():
    """
    Input: trigger_crawl called with tls_verify=False
    Output: session.put called with the TLS config endpoint and value "false"
    Details:
        Verifies that disabling TLS verification causes a PUT request to
        PUT /config/default/http.tls.certificates.check with data="false"
        before any seed or job requests are sent.
    """
    session = _make_session_with_tls()
    trigger_crawl(["http://host1"], crawl_id="tls-01", tls_verify=False, session=session)

    session.put.assert_called_once()
    put_call = session.put.call_args
    url = put_call.args[0] if put_call.args else put_call.kwargs.get("url", "")
    assert "http.tls.certificates.check" in url
    assert put_call.kwargs.get("data") == "false"


def test_tls_patch_not_sent_when_enabled():
    """
    Input: trigger_crawl called with tls_verify=True (default)
    Output: session.put is never called
    Details:
        Verifies that the TLS config PUT is skipped when verification is
        not disabled, so the server's existing config is left unchanged.
    """
    session = _make_session()
    trigger_crawl(["http://host1"], crawl_id="tls-02", tls_verify=True, session=session)

    session.put.assert_not_called()


def _make_fetch_session(nodes=None, stats=None):
    """
    Input:  nodes: list|None — raw FetchNodeDbInfo records to return from GET /db/fetchdb
            stats: dict|None — stats payload to return from POST /db/crawldb
    Output: MagicMock requests.Session
    Details:
        Wires session.get (fetchdb) and session.post (crawldb stats).
    """
    if nodes is None:
        nodes = [
            {
                "url": "http://svc1.local/",
                "status": 200,
                "numOfOutlinks": 2,
                "children": [
                    {"childUrl": "http://svc1.local/about", "anchorText": "About"},
                    {"childUrl": "http://svc1.local/api", "anchorText": "API"},
                ],
            }
        ]
    if stats is None:
        stats = {"totalUrls": 1, "status": {"200": 1}}

    session = MagicMock()

    get_resp = MagicMock()
    get_resp.status_code = 200
    get_resp.json.return_value = nodes
    get_resp.raise_for_status = MagicMock()
    session.get.return_value = get_resp

    post_resp = MagicMock()
    post_resp.status_code = 200
    post_resp.json.return_value = stats
    post_resp.raise_for_status = MagicMock()
    session.post.return_value = post_resp

    return session


def test_fetch_results_returns_nodes_and_stats():
    """
    Input: mock session with one node and stats dict
    Output: result dict has "nodes" and "stats" keys
    Details:
        Verifies the top-level structure of the fetch_results return value.
    """
    session = _make_fetch_session()
    result = fetch_results("cid-10", session=session)
    assert "nodes" in result
    assert "stats" in result


def test_fetch_results_node_structure():
    """
    Input: mock session with one node containing two outlinks
    Output: node record normalised to {url, status, num_outlinks, outlinks}
    Details:
        Verifies that raw FetchNodeDbInfo fields are normalised to snake_case
        and that children are mapped to {url, anchor} outlink dicts.
    """
    session = _make_fetch_session()
    result = fetch_results("cid-11", session=session)

    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    assert node["url"] == "http://svc1.local/"
    assert node["status"] == 200
    assert node["num_outlinks"] == 2
    assert len(node["outlinks"]) == 2
    assert node["outlinks"][0] == {"url": "http://svc1.local/about", "anchor": "About"}


def test_fetch_results_stats_forwarded():
    """
    Input: mock session with custom stats payload
    Output: stats key in result matches the mock response exactly
    Details:
        Verifies that the crawldb stats dict is forwarded unchanged.
    """
    custom_stats = {"totalUrls": 42, "status": {"200": 40, "404": 2}}
    session = _make_fetch_session(stats=custom_stats)
    result = fetch_results("cid-12", session=session)
    assert result["stats"] == custom_stats


def test_fetch_results_empty_nodes():
    """
    Input: mock session returning empty fetchdb list
    Output: result["nodes"] is an empty list
    Details:
        Verifies graceful handling when no URLs were fetched.
    """
    session = _make_fetch_session(nodes=[])
    result = fetch_results("cid-13", session=session)
    assert result["nodes"] == []


def test_fetch_results_crawldb_post_body():
    """
    Input: mock session
    Output: POST /db/crawldb body contains crawlId and type=stats
    Details:
        Verifies the stats query body shape sent to the crawldb endpoint.
    """
    session = _make_fetch_session()
    fetch_results("cid-14", session=session)

    post_call = session.post.call_args
    body = post_call.kwargs.get("json") or post_call.args[1]
    assert body["crawlId"] == "cid-14"
    assert body["type"] == "stats"


def test_fetch_page_text_returns_stripped_text():
    """
    Input: mock HTTP response returning HTML
    Output: visible text with tags stripped, scripts excluded
    """
    from unittest.mock import patch, MagicMock
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
    from unittest.mock import patch
    from flask_app.services.nutch import _fetch_page_text

    with patch("flask_app.services.nutch.requests.get", side_effect=ConnectionError("refused")):
        result = _fetch_page_text("http://example.com/page")

    assert result == "http://example.com/page"
