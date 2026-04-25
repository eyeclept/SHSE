"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Unit tests for flask_app/routes/api.py.
    All OpenSearch calls are mocked; no live services required.
"""
# Imports
import json
import os
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask_app import db

# Globals
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "templates")
_STATIC_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "static")


# Functions
@pytest.fixture
def api_app():
    """
    Input: None
    Output: Flask test app with the api blueprint registered
    Details:
        Uses SQLite in-memory to avoid requiring MariaDB.
    """
    from flask_app.models.user import User                     # noqa: F401
    from flask_app.models.search_history import SearchHistory  # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget  # noqa: F401
    from flask_app.models.crawl_job import CrawlJob            # noqa: F401
    from flask_app.routes.api import api_bp

    app = Flask(
        "test_api",
        template_folder=_TEMPLATE_DIR,
        static_folder=_STATIC_DIR,
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    db.init_app(app)
    app.register_blueprint(api_bp)

    with app.app_context():
        db.create_all()
        yield app


@pytest.fixture
def client(api_app):
    return api_app.test_client()


def _fake_os_response(hits, total=None, took=5, agg_buckets=None):
    """
    Input: hits — list of hit dicts; total — override total count
    Output: dict shaped like an OpenSearch search response
    """
    if total is None:
        total = len(hits)
    return {
        "took": took,
        "hits": {
            "total": {"value": total, "relation": "eq"},
            "hits": hits,
        },
        "aggregations": {
            "by_service": {
                "buckets": agg_buckets or [],
            }
        },
    }


def test_search_empty_query_returns_empty(client):
    """
    Input: GET /api/search with no q param
    Output: 200 JSON with empty results list and total=0
    Details:
        No OpenSearch call should be made for a blank query.
    """
    r = client.get("/api/search")
    assert r.status_code == 200
    data = r.get_json()
    assert data["results"] == []
    assert data["total"] == 0
    assert data["q"] == ""


def test_search_returns_results(client):
    """
    Input: GET /api/search?q=animal with mocked OpenSearch
    Output: 200 JSON with correct result fields populated
    Details:
        Verifies the route maps OpenSearch hit fields to the documented
        response shape correctly.
    """
    fake_hit = {
        "_id": "abc123",
        "_score": 1.8,
        "_source": {
            "title": "Animal",
            "url": "http://kiwix:8082/content/wikipedia/Animal",
            "service_nickname": "kiwix-wikipedia",
            "port": 8082,
            "crawled_at": "2026-04-25T10:00:00",
            "content_type": "text/html",
            "text": "Animals are multicellular eukaryotic organisms.",
            "vectorized": False,
        },
        "highlight": {"text": ["Animals are multicellular eukaryotic organisms."]},
    }
    os_resp = _fake_os_response(
        [fake_hit],
        agg_buckets=[{"key": "kiwix-wikipedia", "doc_count": 1}],
    )

    with patch("flask_app.routes.api.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.search.return_value = os_resp
        mock_get_client.return_value = mock_client

        r = client.get("/api/search?q=animal")

    assert r.status_code == 200
    data = r.get_json()
    assert data["q"] == "animal"
    assert data["total"] == 1
    assert data["took_ms"] == 5
    assert len(data["results"]) == 1

    result = data["results"][0]
    assert result["id"] == "abc123"
    assert result["title"] == "Animal"
    assert result["url"] == "http://kiwix:8082/content/wikipedia/Animal"
    assert result["service"] == "kiwix-wikipedia"
    assert result["port"] == 8082
    assert result["vectorized"] is False
    assert "Animal" in result["snippet"]

    assert data["sources"] == [{"name": "kiwix-wikipedia", "n": 1}]


def test_search_pagination(client):
    """
    Input: GET /api/search?q=test&page=2
    Output: page=2 reflected in response; OpenSearch from= offset is correct
    Details:
        Verifies the route passes the correct from/size offsets to OpenSearch.
    """
    os_resp = _fake_os_response([], total=25)

    with patch("flask_app.routes.api.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.search.return_value = os_resp
        mock_get_client.return_value = mock_client

        r = client.get("/api/search?q=test&page=2")

    assert r.status_code == 200
    data = r.get_json()
    assert data["page"] == 2
    assert data["page_count"] == 3  # ceil(25 / 10)

    call_body = mock_client.search.call_args.kwargs["body"]
    assert call_body["from"] == 10   # page 2, page_size 10
    assert call_body["size"] == 10


def test_search_invalid_page_defaults_to_1(client):
    """
    Input: GET /api/search?q=test&page=notanumber
    Output: 200 with page=1, no crash
    Details:
        Verifies the ValueError from int() is caught and page defaults to 1.
    """
    os_resp = _fake_os_response([])

    with patch("flask_app.routes.api.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.search.return_value = os_resp
        mock_get_client.return_value = mock_client

        r = client.get("/api/search?q=test&page=notanumber")

    assert r.status_code == 200
    assert r.get_json()["page"] == 1


def test_search_opensearch_unreachable_returns_empty(client):
    """
    Input: GET /api/search?q=test with OpenSearch raising an exception
    Output: 200 with empty results and total=0, no 500 error
    Details:
        Verifies the route handles OpenSearch connection failures gracefully.
    """
    with patch("flask_app.routes.api.get_client", side_effect=Exception("connection refused")):
        r = client.get("/api/search?q=test")

    assert r.status_code == 200
    data = r.get_json()
    assert data["results"] == []
    assert data["total"] == 0


def test_stats_returns_counts(client):
    """
    Input: GET /api/stats with mocked OpenSearch
    Output: 200 JSON with docs, services, and last_crawl fields
    """
    with patch("flask_app.routes.api.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.count.return_value = {"count": 1402}
        mock_client.search.side_effect = [
            {"aggregations": {"svc": {"value": 6}}},
            {"hits": {"hits": [{"_source": {"crawled_at": "2026-04-25T10:00:00"}}]}},
        ]
        mock_get_client.return_value = mock_client

        r = client.get("/api/stats")

    assert r.status_code == 200
    data = r.get_json()
    assert data["docs"] == 1402
    assert data["services"] == 6
    assert data["last_crawl"] == "2026-04-25T10:00:00"


def test_stats_opensearch_unreachable_returns_zeros(client):
    """
    Input: GET /api/stats with OpenSearch unavailable
    Output: 200 JSON with zeros, no 500 error
    """
    with patch("flask_app.routes.api.get_client", side_effect=Exception("down")):
        r = client.get("/api/stats")

    assert r.status_code == 200
    data = r.get_json()
    assert data["docs"] == 0
    assert data["services"] == 0
    assert data["last_crawl"] is None


def test_highlight_stripped_of_html_tags(client):
    """
    Input: GET /api/search?q=animal — OpenSearch returns highlights with empty tags
    Output: snippet in JSON response contains plain text, not HTML markup
    Details:
        The API uses empty pre/post tags so highlights are plain text.
        Verifies no leftover angle-bracket tags leak into the snippet field.
    """
    fake_hit = {
        "_id": "xyz",
        "_score": 1.0,
        "_source": {
            "title": "Animal",
            "url": "http://host/animal",
            "service_nickname": "test",
            "port": 80,
            "crawled_at": "2026-04-25T00:00:00",
            "content_type": "text/html",
            "text": "Animals are diverse.",
            "vectorized": False,
        },
        "highlight": {"text": ["Animals are diverse."]},
    }
    os_resp = _fake_os_response([fake_hit])

    with patch("flask_app.routes.api.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.search.return_value = os_resp
        mock_get_client.return_value = mock_client

        r = client.get("/api/search?q=animal")

    snippet = r.get_json()["results"][0]["snippet"]
    assert "<" not in snippet
    assert ">" not in snippet
