"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for task 17b — date/time answer card detection and resolution.
    All time-sensitive assertions use freezegun or unittest.mock.patch to
    produce deterministic results. NTP tests mock ntplib.NTPClient.
"""
# Imports
import logging
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from flask_app.services.datetime_cards import (
    build_datetime_card,
    detect_date_query,
    get_current_time,
    resolve_date_query,
)

# Globals
logger = logging.getLogger(__name__)

# Fixed "now" used throughout: Monday 5 May 2025, 14:30 UTC
_FIXED_UTC = datetime(2025, 5, 5, 14, 30, 0, tzinfo=timezone.utc)
_FIXED_LOCAL = _FIXED_UTC.astimezone()
_FIXED_DATE = _FIXED_LOCAL.date()


# ── detect_date_query ──────────────────────────────────────────────────────────

def test_detect_today():
    result = detect_date_query("what's today's date")
    assert result is not None
    assert result["intent"] == "today"


def test_detect_today_variants():
    for q in ["what day is today", "today's date", "current date", "what is today's date"]:
        assert detect_date_query(q) is not None, f"Failed to detect: {q!r}"


def test_detect_day_was():
    result = detect_date_query("what day of the week was 1 january 1970")
    assert result is not None
    assert result["intent"] == "day_was"
    assert result["date"] == date(1970, 1, 1)


def test_detect_day_was_without_week_phrase():
    result = detect_date_query("what day was 4 july 1776")
    assert result is not None
    assert result["intent"] == "day_was"


def test_detect_days_until():
    result = detect_date_query("how many days until christmas")
    assert result is not None
    assert result["intent"] == "days_until"


def test_detect_days_since():
    result = detect_date_query("how many days since 1 january 2020")
    assert result is not None
    assert result["intent"] == "days_since"


def test_detect_week_number():
    result = detect_date_query("what week number is it")
    assert result is not None
    assert result["intent"] == "week_number"


def test_detect_leap_year():
    result = detect_date_query("is 2024 a leap year")
    assert result is not None
    assert result["intent"] == "leap_year"
    assert result["year"] == 2024


def test_detect_none_for_plain_query():
    assert detect_date_query("human anatomy") is None


def test_detect_none_for_calculator_expression():
    # A math expression should not be detected as a date query
    assert detect_date_query("2 + 2") is None


# ── resolve_date_query ─────────────────────────────────────────────────────────

@patch("flask_app.services.datetime_cards.get_current_time", return_value=_FIXED_LOCAL)
def test_resolve_today(mock_now):
    query = {"intent": "today", "date": None, "label": "Today's date"}
    result = resolve_date_query(query)
    assert "Monday" in result["body"]
    assert "2025" in result["body"]


def test_resolve_day_was_thursday():
    # 1 January 1970 was a Thursday
    query = {"intent": "day_was", "date": date(1970, 1, 1), "label": "Day of the week"}
    result = resolve_date_query(query)
    assert "Thursday" in result["body"]


def test_resolve_days_until_future():
    target = date(2099, 12, 25)
    query = {"intent": "days_until", "date": target, "label": "Days until Christmas"}
    result = resolve_date_query(query)
    # Should mention a positive number of days
    assert any(c.isdigit() for c in result["body"])
    assert "ago" not in result["body"].lower()


def test_resolve_days_until_past_shows_ago():
    target = date(2000, 1, 1)
    query = {"intent": "days_until", "date": target, "label": "Days until New Year"}
    result = resolve_date_query(query)
    assert "ago" in result["body"].lower()


def test_resolve_days_since():
    # 1 Jan 2020 is firmly in the past
    target = date(2020, 1, 1)
    query = {"intent": "days_since", "date": target, "label": "Days since New Year 2020"}
    result = resolve_date_query(query)
    assert any(c.isdigit() for c in result["body"])


@patch("flask_app.services.datetime_cards.get_current_time", return_value=_FIXED_LOCAL)
def test_resolve_week_number(mock_now):
    query = {"intent": "week_number", "date": None, "label": "Week number"}
    result = resolve_date_query(query)
    assert "Week" in result["body"]
    assert "2025" in result["body"]


def test_resolve_leap_year_2024_is_leap():
    query = {"intent": "leap_year", "year": 2024, "label": "Leap Year: 2024"}
    result = resolve_date_query(query)
    assert "Yes" in result["body"]
    assert "2024" in result["body"]


def test_resolve_leap_year_2023_not_leap():
    query = {"intent": "leap_year", "year": 2023, "label": "Leap Year: 2023"}
    result = resolve_date_query(query)
    assert "No" in result["body"]


# ── get_current_time ───────────────────────────────────────────────────────────

def test_get_current_time_no_ntp_returns_datetime():
    result = get_current_time(ntp_server=None)
    assert isinstance(result, datetime)
    assert result.tzinfo is not None


def test_get_current_time_with_mocked_ntp():
    mock_response = MagicMock()
    mock_response.tx_time = _FIXED_UTC.timestamp()

    with patch("flask_app.services.datetime_cards._ntplib") as mock_ntplib:
        mock_ntplib.NTPClient.return_value.request.return_value = mock_response
        result = get_current_time(ntp_server="pool.ntp.org")

    assert isinstance(result, datetime)
    # Should be close to our fixed UTC time (within 1 second after tz conversion)
    assert abs(result.timestamp() - _FIXED_UTC.timestamp()) < 1


# ── build_datetime_card ────────────────────────────────────────────────────────

@patch("flask_app.services.datetime_cards.get_current_time", return_value=_FIXED_LOCAL)
def test_build_datetime_card_today(mock_now):
    card, ctx = build_datetime_card("what's today's date")
    assert card is not None
    assert card["type"] == "datetime"
    assert "label" in card
    assert "body" in card
    assert "source" in card
    assert ctx is not None
    assert "Monday" in card["body"]


def test_build_datetime_card_no_match():
    card, ctx = build_datetime_card("human anatomy")
    assert card is None
    assert ctx is None


@patch("flask_app.services.datetime_cards.get_current_time", return_value=_FIXED_LOCAL)
def test_build_datetime_card_ai_context_prepended(mock_now):
    card, ctx = build_datetime_card("what's today's date")
    assert ctx is not None
    assert len(ctx) > 0


if __name__ == "__main__":
    pass
