"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Inline answer card dispatcher. Tries each adapter in priority order and
    returns the first match as (answer_card, ai_context). Adapters:
      1. Dictionary (OED via stardict.py)
      2. Date / time (datetime_cards.py)
      3. Calculator (calculator_cards.py)

    All adapters share the same return contract: (dict|None, str|None).
    Callers import build_inline_card() from this module rather than
    importing individual adapters directly.
"""
# Imports
import logging

from flask_app.services.calculator_cards import build_calculator_card
from flask_app.services.datetime_cards import build_datetime_card
from flask_app.services.stardict import build_definition_card
from flask_app.services.translate import build_translate_card
from flask_app.services.unit_converter_cards import build_unit_converter_card
from flask_app.services.weather_cards import build_weather_card

# Globals
logger = logging.getLogger(__name__)

_ADAPTERS = [
    ("definition",    build_definition_card),
    ("translation",   build_translate_card),
    ("datetime",      build_datetime_card),
    ("calculator",    build_calculator_card),
    ("unit_converter",build_unit_converter_card),
    ("weather",       build_weather_card),
]


# Functions
def build_inline_card(q: str) -> tuple:
    """
    Input: q — raw search query string
    Output: (answer_card dict, ai_context str) or (None, None)
    Details:
        Iterates adapters in priority order. Returns on the first non-None
        answer_card. If all adapters return None, returns (None, None).
        Each adapter failure is logged at WARNING and skipped rather than
        propagating upward.
    """
    if not q:
        return None, None

    for name, adapter in _ADAPTERS:
        try:
            card, ctx = adapter(q)
            if card is not None:
                return card, ctx
        except Exception:
            logger.warning("inline adapter '%s' raised unexpectedly", name, exc_info=True)

    return None, None


if __name__ == "__main__":
    pass
