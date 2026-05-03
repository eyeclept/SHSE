"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for flask_app/services/llm.py.
    All tests use a mock session; no live LLM API required.
"""
# Imports
from unittest.mock import MagicMock

import pytest

from flask_app.services.llm import get_embedding, generate_summary, rewrite_query

# Globals

# Functions
def _mock_session(json_body, status_code=200, raise_exc=None):
    """
    Input:
        json_body   - dict to return from resp.json()
        status_code - int HTTP status
        raise_exc   - if set, post() raises this exception instead
    Output:
        MagicMock requests.Session
    Details:
        Builds a minimal mock that satisfies the call pattern in llm.py.
    """
    session = MagicMock()
    if raise_exc:
        session.post.side_effect = raise_exc
        return session
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        resp.raise_for_status.return_value = None
    session.post.return_value = resp
    return session


def test_embedding_returns_vector():
    """
    Input: None
    Output: None
    Details:
        get_embedding returns a float list of the expected dimension.
    """
    vector = [0.1] * 768
    session = _mock_session({"data": [{"embedding": vector}]})
    result = get_embedding("test text", session=session)
    assert isinstance(result, list)
    assert len(result) == 768
    assert result[0] == pytest.approx(0.1)


def test_embedding_returns_none_on_connection_error():
    """
    Input: None
    Output: None
    Details:
        get_embedding returns None (no exception) when endpoint is unreachable.
    """
    session = _mock_session({}, raise_exc=ConnectionError("refused"))
    result = get_embedding("test text", session=session)
    assert result is None


def test_embedding_returns_none_on_http_error():
    """
    Input: None
    Output: None
    Details:
        get_embedding returns None when the server returns 4xx/5xx.
    """
    session = _mock_session({}, status_code=503)
    result = get_embedding("test text", session=session)
    assert result is None


def test_embedding_returns_none_on_error_field():
    """
    Input: None
    Output: None
    Details:
        get_embedding returns None when the response body contains an error field.
    """
    session = _mock_session({"error": {"message": "model not found"}})
    result = get_embedding("test text", session=session)
    assert result is None


def test_summary_returns_string():
    """
    Input: None
    Output: None
    Details:
        generate_summary returns a non-empty string on success.
    """
    body = {"choices": [{"message": {"content": "This is the summary."}}]}
    session = _mock_session(body)
    result = generate_summary(["chunk one", "chunk two"], "what is x?", session=session)
    assert isinstance(result, str)
    assert len(result) > 0


def test_summary_returns_none_on_connection_error():
    """
    Input: None
    Output: None
    Details:
        generate_summary returns None (no exception) when endpoint unreachable.
    """
    session = _mock_session({}, raise_exc=ConnectionError("refused"))
    result = generate_summary(["chunk"], "query", session=session)
    assert result is None


def test_summary_returns_none_on_error_field():
    """
    Input: None
    Output: None
    Details:
        generate_summary returns None when the response contains an error field.
    """
    session = _mock_session({"error": {"message": "quota exceeded"}})
    result = generate_summary(["chunk"], "query", session=session)
    assert result is None


def test_rewrite_query_returns_model_response():
    """
    Input: None
    Output: None
    Details:
        rewrite_query returns the model's stripped response on success.
    """
    body = {"choices": [{"message": {"content": "  server config  "}}]}
    session = _mock_session(body)
    result = rewrite_query("please tell me about how to configure a server", session=session)
    assert result == "server config"


def test_rewrite_query_returns_raw_on_connection_failure():
    """
    Input: None
    Output: None
    Details:
        rewrite_query returns raw_query unchanged when the endpoint is unreachable.
    """
    session = _mock_session({}, raise_exc=ConnectionError("refused"))
    raw = "please find me server info"
    result = rewrite_query(raw, session=session)
    assert result == raw


def test_rewrite_query_returns_raw_on_empty_response():
    """
    Input: None
    Output: None
    Details:
        rewrite_query returns raw_query when the model returns an empty string.
    """
    body = {"choices": [{"message": {"content": "   "}}]}
    session = _mock_session(body)
    raw = "what is dns"
    result = rewrite_query(raw, session=session)
    assert result == raw


def test_rewrite_query_returns_raw_on_error_field():
    """
    Input: None
    Output: None
    Details:
        rewrite_query returns raw_query when the response body contains an error field.
    """
    session = _mock_session({"error": {"message": "model not found"}})
    raw = "show me all containers"
    result = rewrite_query(raw, session=session)
    assert result == raw


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
