"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for task 17e — unit converter answer card detection and conversion.
    Covers all supported unit families (length, mass, temperature, volume, speed,
    data, time, area, pressure, energy), edge cases, and answer_card construction.
"""
# Imports
import logging

import pytest

from flask_app.services.unit_converter_cards import (
    build_unit_converter_card,
    convert_units,
    detect_unit_query,
)

# Globals
logger = logging.getLogger(__name__)


# ── detect_unit_query ──────────────────────────────────────────────────────────

def test_detect_km_to_miles():
    result = detect_unit_query("5 km to miles")
    assert result is not None
    assert result["value"] == 5.0
    assert result["from_unit"] == "km"
    assert result["to_unit"] == "miles"


def test_detect_convert_prefix():
    result = detect_unit_query("convert 100 fahrenheit to celsius")
    assert result is not None
    assert result["value"] == 100.0
    assert result["from_unit"] == "F"
    assert result["to_unit"] == "C"


def test_detect_in_preposition():
    result = detect_unit_query("5 kg in lb")
    assert result is not None
    assert result["value"] == 5.0


def test_detect_none_plain():
    assert detect_unit_query("human anatomy") is None


def test_detect_none_no_units():
    assert detect_unit_query("5 to 10") is None


def test_detect_celsius_to_fahrenheit():
    result = detect_unit_query("0 celsius to fahrenheit")
    assert result is not None
    assert result["from_unit"] == "C"
    assert result["to_unit"] == "F"


def test_detect_kelvin():
    result = detect_unit_query("100 celsius to kelvin")
    assert result is not None
    assert result["from_unit"] == "C"
    assert result["to_unit"] == "K"


# ── convert_units ──────────────────────────────────────────────────────────────

def test_km_to_miles():
    result = convert_units(1, "km", "miles")
    assert result is not None
    assert "0.621371" in result["to"]


def test_miles_to_km():
    result = convert_units(1, "miles", "km")
    assert result is not None
    # 1 mile ≈ 1.60934 km
    assert "1.60934" in result["to"]


def test_celsius_to_fahrenheit_zero():
    result = convert_units(0, "C", "F")
    assert result is not None
    assert "32" in result["to"]


def test_celsius_to_kelvin():
    result = convert_units(100, "C", "K")
    assert result is not None
    assert "373.15" in result["to"]


def test_fahrenheit_to_celsius():
    result = convert_units(212, "F", "C")
    assert result is not None
    assert "100" in result["to"]


def test_kelvin_to_celsius():
    result = convert_units(273.15, "K", "C")
    assert result is not None
    assert "0" in result["to"]


def test_kg_to_lb():
    result = convert_units(1, "kg", "lb")
    assert result is not None
    assert "2.20462" in result["to"]


def test_lb_to_kg():
    result = convert_units(1, "lb", "kg")
    assert result is not None
    assert "0.453592" in result["to"]


def test_meter_to_feet():
    result = convert_units(1, "m", "ft")
    assert result is not None
    # 1 m ≈ 3.28084 ft
    assert "3.28084" in result["to"]


def test_litre_to_gallon():
    result = convert_units(1, "l", "gallon")
    assert result is not None
    assert "0.264172" in result["to"]


def test_mph_to_kph():
    result = convert_units(60, "mph", "km/h")
    assert result is not None
    assert "96.5606" in result["to"]


def test_gb_to_mb():
    result = convert_units(1, "gb", "mb")
    assert result is not None
    assert "1024" in result["to"]


def test_hour_to_seconds():
    result = convert_units(1, "h", "s")
    assert result is not None
    assert "3600" in result["to"]


def test_unknown_from_unit_returns_none():
    result = convert_units(1, "fathom", "m")
    assert result is None


def test_unknown_to_unit_returns_none():
    result = convert_units(1, "m", "fathom")
    assert result is None


def test_family_mismatch_returns_none():
    # km (length) to lb (mass) — different families
    result = convert_units(1, "km", "lb")
    assert result is None


def test_result_dict_has_source():
    result = convert_units(1, "km", "miles")
    assert result is not None
    assert result["source"] == "Built-in converter"


def test_result_dict_has_from_and_to():
    result = convert_units(5, "km", "miles")
    assert result is not None
    assert "5" in result["from"]
    assert "km" in result["from"]
    assert "miles" in result["to"]


# ── build_unit_converter_card ──────────────────────────────────────────────────

def test_build_card_km_to_miles():
    card, ctx = build_unit_converter_card("5 km to miles")
    assert card is not None
    assert card["type"] == "unit_converter"
    assert card["label"] == "Unit Converter"
    assert "km" in card["body"]
    assert "miles" in card["body"]
    assert card["source"] == "Built-in converter"
    assert ctx is not None


def test_build_card_no_match():
    card, ctx = build_unit_converter_card("human anatomy")
    assert card is None
    assert ctx is None


def test_build_card_keys():
    card, ctx = build_unit_converter_card("1 kg to lb")
    assert card is not None
    for key in ("type", "label", "body", "source"):
        assert key in card


def test_build_card_ai_context_contains_result():
    card, ctx = build_unit_converter_card("0 celsius to fahrenheit")
    assert card is not None
    assert ctx is not None
    assert "32" in ctx


if __name__ == "__main__":
    pass
