"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for task 17f — offline translation answer card.
    All Ollama/HTTP calls are mocked with unittest.mock.patch.
    No real network requests are made.
"""
# Imports
import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from flask_app.services.translate import (
    build_translate_card,
    detect_translate_query,
    translate_text,
)

# Globals
logger = logging.getLogger(__name__)


# ── detect_translate_query ─────────────────────────────────────────────────────

def test_detect_translate_basic():
    result = detect_translate_query("translate hello to Spanish")
    assert result is not None
    assert result["text"] == "hello"
    assert result["target_lang"] == "Spanish"


def test_detect_how_do_you_say():
    result = detect_translate_query("how do you say goodbye in French")
    assert result is not None
    assert result["text"] == "goodbye"
    assert result["target_lang"] == "French"


def test_detect_what_is_in():
    result = detect_translate_query("what is dog in Japanese")
    assert result is not None
    assert result["text"] == "dog"
    assert result["target_lang"] == "Japanese"


def test_detect_none_plain():
    assert detect_translate_query("hello") is None


def test_detect_none_define():
    assert detect_translate_query("define hello") is None


def test_detect_none_calculator():
    assert detect_translate_query("2 + 2") is None


def test_detect_translate_with_phrase():
    result = detect_translate_query("translate good morning to German")
    assert result is not None
    assert "morning" in result["text"]
    assert result["target_lang"] == "German"


# ── translate_text ─────────────────────────────────────────────────────────────

def _make_ok_response(translation: str):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": translation}}]
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def test_translate_text_returns_translation():
    with patch("flask_app.services.translate._requests.post", return_value=_make_ok_response("Hola")):
        result = translate_text("hello", "Spanish")
    assert result == "Hola"


def test_translate_text_timeout_returns_none(caplog):
    with patch("flask_app.services.translate._requests.post",
               side_effect=requests.exceptions.Timeout):
        with caplog.at_level(logging.WARNING, logger="flask_app.services.translate"):
            result = translate_text("hello", "Spanish")
    assert result is None
    assert any("timed out" in r.message for r in caplog.records)


def test_translate_text_network_error_returns_none(caplog):
    with patch("flask_app.services.translate._requests.post",
               side_effect=requests.exceptions.ConnectionError("refused")):
        with caplog.at_level(logging.WARNING, logger="flask_app.services.translate"):
            result = translate_text("hello", "Spanish")
    assert result is None
    assert any("network" in r.message.lower() for r in caplog.records)


def test_translate_text_bad_json_returns_none(caplog):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.side_effect = ValueError("not JSON")
    with patch("flask_app.services.translate._requests.post", return_value=mock_resp):
        with caplog.at_level(logging.WARNING, logger="flask_app.services.translate"):
            result = translate_text("hello", "Spanish")
    assert result is None


def test_translate_text_missing_choices_returns_none(caplog):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"choices": []}
    with patch("flask_app.services.translate._requests.post", return_value=mock_resp):
        with caplog.at_level(logging.WARNING, logger="flask_app.services.translate"):
            result = translate_text("hello", "Spanish")
    assert result is None


# ── build_translate_card ───────────────────────────────────────────────────────

def test_build_card_returns_card():
    with patch("flask_app.services.translate._requests.post",
               return_value=_make_ok_response("Hola")):
        card, ctx = build_translate_card("translate hello to Spanish")
    assert card is not None
    assert card["type"] == "translation"
    assert card["word"] == "hello"
    assert card["body"] == "Hola"
    assert card["target_lang"] == "Spanish"
    assert "source" in card


def test_build_card_none_for_plain():
    card, ctx = build_translate_card("hello")
    assert card is None
    assert ctx is None


def test_build_card_none_when_translation_fails():
    with patch("flask_app.services.translate._requests.post",
               side_effect=requests.exceptions.ConnectionError):
        card, ctx = build_translate_card("translate hello to Spanish")
    assert card is None
    assert ctx is None


def test_build_card_keys():
    with patch("flask_app.services.translate._requests.post",
               return_value=_make_ok_response("Bonjour")):
        card, ctx = build_translate_card("translate hello to French")
    assert card is not None
    for key in ("type", "word", "body", "target_lang", "source"):
        assert key in card


def test_build_card_ai_context():
    with patch("flask_app.services.translate._requests.post",
               return_value=_make_ok_response("Bonjour")):
        card, ctx = build_translate_card("translate hello to French")
    assert ctx is not None
    assert "Bonjour" in ctx
    assert "hello" in ctx


if __name__ == "__main__":
    pass
