"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for task 17d — calculator answer card detection and evaluation.
    Covers arithmetic, math functions, factorial, AST security blocking,
    and answer_card / ai_context construction.
"""
# Imports
import logging

import pytest

from flask_app.services.calculator_cards import (
    build_calculator_card,
    detect_calc_query,
    evaluate_expression,
)

# Globals
logger = logging.getLogger(__name__)


# ── detect_calc_query ──────────────────────────────────────────────────────────

def test_detect_what_is():
    result = detect_calc_query("what is 2 + 2")
    assert result == "2 + 2"


def test_detect_calculate():
    result = detect_calc_query("calculate 5 * 8")
    assert result == "5 * 8"


def test_detect_compute():
    result = detect_calc_query("compute 10 / 2")
    assert result == "10 / 2"


def test_detect_bare_expression():
    result = detect_calc_query("3 ** 10")
    assert result == "3 ** 10"


def test_detect_trailing_equals():
    result = detect_calc_query("12 / 4 =")
    assert result is not None
    assert "=" not in result
    assert "12" in result


def test_detect_sqrt():
    result = detect_calc_query("sqrt(144)")
    assert result is not None
    assert "sqrt" in result


def test_detect_modulo():
    result = detect_calc_query("17 % 5")
    assert result is not None


def test_detect_none_plain_text():
    assert detect_calc_query("human anatomy") is None


def test_detect_none_no_operator():
    # A bare number with no operator should not be detected
    assert detect_calc_query("42") is None


# ── evaluate_expression ────────────────────────────────────────────────────────

def test_eval_addition():
    result = evaluate_expression("2 + 2")
    assert result is not None
    assert result["result"] == "4"


def test_eval_subtraction():
    result = evaluate_expression("10 - 3")
    assert result is not None
    assert result["result"] == "7"


def test_eval_multiplication():
    result = evaluate_expression("5 * 8")
    assert result is not None
    assert result["result"] == "40"


def test_eval_division():
    result = evaluate_expression("10 / 4")
    assert result is not None
    assert result["result"] == "2.5"


def test_eval_floor_division():
    result = evaluate_expression("10 // 3")
    assert result is not None
    assert result["result"] == "3"


def test_eval_power():
    result = evaluate_expression("2 ** 10")
    assert result is not None
    assert result["result"] == "1024"


def test_eval_modulo():
    result = evaluate_expression("17 % 5")
    assert result is not None
    assert result["result"] == "2"


def test_eval_zero_division_returns_none():
    result = evaluate_expression("10 / 0")
    assert result is None


def test_eval_blocked_import():
    result = evaluate_expression("__import__('os')")
    assert result is None


def test_eval_blocked_builtin_call():
    result = evaluate_expression("open('etc/passwd')")
    assert result is None


def test_eval_sqrt():
    result = evaluate_expression("sqrt(144)")
    assert result is not None
    assert result["result"] == "12"


def test_eval_factorial():
    result = evaluate_expression("factorial(10)")
    assert result is not None
    assert result["result"] == "3628800"


def test_eval_factorial_word_shorthand():
    result = evaluate_expression("10 factorial")
    assert result is not None
    assert result["result"] == "3628800"


def test_eval_factorial_bang_shorthand():
    result = evaluate_expression("10!")
    assert result is not None
    assert result["result"] == "3628800"


def test_eval_caret_power():
    # "^" is a common user expectation for exponentiation
    result = evaluate_expression("2^8")
    assert result is not None
    assert result["result"] == "256"


def test_eval_pi_constant():
    result = evaluate_expression("pi * 2")
    assert result is not None
    # Should be close to 6.283...
    assert abs(float(result["result"]) - 6.283185307179586) < 1e-9


def test_eval_abs():
    result = evaluate_expression("abs(-7)")
    assert result is not None
    assert result["result"] == "7"


def test_eval_nested_expression():
    result = evaluate_expression("(2 + 3) * 4")
    assert result is not None
    assert result["result"] == "20"


# ── build_calculator_card ──────────────────────────────────────────────────────

def test_build_card_what_is_2_plus_2():
    card, ctx = build_calculator_card("what is 2 + 2")
    assert card is not None
    assert card["type"] == "calculator"
    assert card["label"] == "Calculator"
    assert "2 + 2" in card["body"]
    assert "4" in card["body"]
    assert card["source"] == "Python"
    assert ctx is not None
    assert "4" in ctx


def test_build_card_no_match_plain_text():
    card, ctx = build_calculator_card("human anatomy")
    assert card is None
    assert ctx is None


def test_build_card_answer_card_keys():
    card, ctx = build_calculator_card("calculate 10 * 10")
    assert card is not None
    for key in ("type", "label", "body", "source"):
        assert key in card, f"Missing key: {key}"


def test_build_card_ai_context_contains_result():
    card, ctx = build_calculator_card("what is 144 / 12")
    assert card is not None
    assert ctx is not None
    assert "12" in ctx


def test_build_card_zero_division_returns_none():
    card, ctx = build_calculator_card("what is 5 / 0")
    assert card is None
    assert ctx is None


if __name__ == "__main__":
    pass
