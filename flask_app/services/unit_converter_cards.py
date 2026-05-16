"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Unit converter answer card service. Detects queries like "5 km to miles"
    or "convert 100 fahrenheit to celsius" and computes the conversion locally
    using a factor table for linear families and explicit formulas for
    temperature. No external service or LLM required.
"""
# Imports
import logging
import re
from typing import Optional

# Globals
logger = logging.getLogger(__name__)

# ── Unit factor tables (unit → SI base unit multiplier) ──────────────────────
# Length: base = metre
_LENGTH = {
    "mm": 0.001, "millimeter": 0.001, "millimetre": 0.001,
    "cm": 0.01, "centimeter": 0.01, "centimetre": 0.01,
    "m": 1.0, "meter": 1.0, "metre": 1.0,
    "km": 1000.0, "kilometer": 1000.0, "kilometre": 1000.0,
    "in": 0.0254, "inch": 0.0254, "inches": 0.0254,
    "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
    "yd": 0.9144, "yard": 0.9144, "yards": 0.9144,
    "mi": 1609.344, "mile": 1609.344, "miles": 1609.344,
    "nmi": 1852.0, "nautical mile": 1852.0,
}

# Mass: base = kilogram
_MASS = {
    "mg": 1e-6, "milligram": 1e-6, "milligramme": 1e-6,
    "g": 0.001, "gram": 0.001, "gramme": 0.001,
    "kg": 1.0, "kilogram": 1.0, "kilogramme": 1.0,
    "t": 1000.0, "tonne": 1000.0, "metric ton": 1000.0,
    "oz": 0.028349523, "ounce": 0.028349523, "ounces": 0.028349523,
    "lb": 0.45359237, "pound": 0.45359237, "pounds": 0.45359237, "lbs": 0.45359237,
    "st": 6.35029318, "stone": 6.35029318,
    "ton": 907.18474, "short ton": 907.18474,
}

# Volume: base = litre
_VOLUME = {
    "ml": 0.001, "milliliter": 0.001, "millilitre": 0.001,
    "l": 1.0, "liter": 1.0, "litre": 1.0,
    "fl oz": 0.0295735, "fluid oz": 0.0295735, "fluid ounce": 0.0295735,
    "cup": 0.236588,
    "pt": 0.473176, "pint": 0.473176, "pints": 0.473176,
    "qt": 0.946353, "quart": 0.946353, "quarts": 0.946353,
    "gal": 3.78541, "gallon": 3.78541, "gallons": 3.78541,
}

# Speed: base = m/s
_SPEED = {
    "m/s": 1.0, "mps": 1.0, "meters per second": 1.0,
    "km/h": 1.0 / 3.6, "kph": 1.0 / 3.6, "kmh": 1.0 / 3.6, "kilometers per hour": 1.0 / 3.6,
    "mph": 0.44704, "miles per hour": 0.44704,
    "knot": 0.514444, "knots": 0.514444, "kn": 0.514444,
}

# Data: base = byte
_DATA = {
    "bit": 0.125,
    "byte": 1.0, "b": 1.0,
    "kb": 1024.0, "kilobyte": 1024.0,
    "mb": 1024.0 ** 2, "megabyte": 1024.0 ** 2,
    "gb": 1024.0 ** 3, "gigabyte": 1024.0 ** 3,
    "tb": 1024.0 ** 4, "terabyte": 1024.0 ** 4,
    "kib": 1024.0, "mib": 1024.0 ** 2, "gib": 1024.0 ** 3, "tib": 1024.0 ** 4,
}

# Time: base = second
_TIME = {
    "s": 1.0, "sec": 1.0, "second": 1.0, "seconds": 1.0,
    "min": 60.0, "minute": 60.0, "minutes": 60.0,
    "h": 3600.0, "hr": 3600.0, "hour": 3600.0, "hours": 3600.0,
    "day": 86400.0, "days": 86400.0,
    "week": 604800.0, "weeks": 604800.0,
}

# Area: base = square metre
_AREA = {
    "mm²": 1e-6, "mm2": 1e-6,
    "cm²": 1e-4, "cm2": 1e-4,
    "m²": 1.0, "m2": 1.0,
    "km²": 1e6, "km2": 1e6,
    "in²": 0.00064516, "in2": 0.00064516,
    "ft²": 0.092903, "ft2": 0.092903,
    "ac": 4046.86, "acre": 4046.86, "acres": 4046.86,
    "ha": 10000.0, "hectare": 10000.0, "hectares": 10000.0,
}

# Pressure: base = pascal
_PRESSURE = {
    "pa": 1.0, "pascal": 1.0,
    "kpa": 1000.0, "kilopascal": 1000.0,
    "mpa": 1e6, "megapascal": 1e6,
    "bar": 1e5,
    "psi": 6894.76, "pound per square inch": 6894.76,
    "atm": 101325.0, "atmosphere": 101325.0,
}

# Energy: base = joule
_ENERGY = {
    "j": 1.0, "joule": 1.0,
    "kj": 1000.0, "kilojoule": 1000.0,
    "cal": 4.184, "calorie": 4.184,
    "kcal": 4184.0, "kilocalorie": 4184.0,
    "wh": 3600.0, "watt hour": 3600.0,
    "kwh": 3.6e6, "kilowatt hour": 3.6e6,
}

_FAMILIES = [_LENGTH, _MASS, _VOLUME, _SPEED, _DATA, _TIME, _AREA, _PRESSURE, _ENERGY]

# Canonical unit name → display label (for clean output)
_CANONICAL = {}
for _fam in _FAMILIES:
    for _k in _fam:
        if len(_k) <= 6 and " " not in _k:
            _CANONICAL[_k] = _k

# Temperature aliases (handled separately — non-linear)
_TEMP_ALIASES = {
    "c": "C", "celsius": "C", "degrees celsius": "C", "°c": "C",
    "f": "F", "fahrenheit": "F", "degrees fahrenheit": "F", "°f": "F",
    "k": "K", "kelvin": "K",
}

# Detection regex: optional "convert", number, from-unit, "to"/"in", to-unit
_RE_UNIT = re.compile(
    r"(?:convert\s+)?"
    r"([\d,]+(?:\.\d+)?)\s+"
    r"([\w/°²²³\s]{1,25}?)\s+"
    r"(?:to|in)\s+"
    r"([\w/°²²³\s]{1,25}?)"
    r"\s*$",
    re.IGNORECASE,
)


# Functions
def _find_factor(unit: str):
    """
    Input: unit string (normalised to lower)
    Output: (factor, family_dict) tuple or (None, None)
    Details:
        Searches all linear families for the unit key. Temperature handled
        separately; this function never matches temperature units.
    """
    for fam in _FAMILIES:
        if unit in fam:
            return fam[unit], fam
    return None, None


def _normalise_unit(unit: str) -> str:
    """Strip extra whitespace, lower-case for lookup."""
    return " ".join(unit.strip().lower().split())


def detect_unit_query(q: str) -> Optional[dict]:
    """
    Input: q — raw search query string
    Output: dict {value, from_unit, to_unit} or None
    Details:
        Matches patterns like "5 km to miles" or "convert 100 F to C".
        Normalises unit strings and resolves temperature aliases.
        Returns None when the query does not match the pattern or units
        are unrecognised.
    """
    m = _RE_UNIT.match(q.strip())
    if not m:
        return None

    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None

    from_raw = _normalise_unit(m.group(2))
    to_raw   = _normalise_unit(m.group(3))

    # Resolve temperature aliases
    from_temp = _TEMP_ALIASES.get(from_raw)
    to_temp   = _TEMP_ALIASES.get(to_raw)

    if from_temp or to_temp:
        # Both must be temperature units for the card to fire
        if from_temp and to_temp:
            return {"value": value, "from_unit": from_temp, "to_unit": to_temp}
        return None

    # Linear family: verify both units exist in the same family
    from_factor, from_fam = _find_factor(from_raw)
    to_factor,   to_fam   = _find_factor(to_raw)

    if from_factor is None or to_factor is None:
        return None
    if from_fam is not to_fam:
        return None

    return {"value": value, "from_unit": from_raw, "to_unit": to_raw}


def convert_units(value: float, from_unit: str, to_unit: str) -> Optional[dict]:
    """
    Input: value (float), from_unit (str), to_unit (str)
    Output: dict {from, to, source} or None
    Details:
        For temperature uses explicit formulas. For all other families converts
        through the SI base unit: result = value * from_factor / to_factor.
        Returns None for unknown units (logs warning).
    """
    from_norm = _normalise_unit(from_unit)
    to_norm   = _normalise_unit(to_unit)

    # Temperature
    from_temp = _TEMP_ALIASES.get(from_norm)
    to_temp   = _TEMP_ALIASES.get(to_norm)

    if from_temp or to_temp:
        fu = from_temp or from_norm.upper()
        tu = to_temp   or to_norm.upper()
        try:
            result = _convert_temperature(value, fu, tu)
        except ValueError as exc:
            logger.warning("Temperature conversion failed: %s", exc)
            return None
        return {
            "from":   f"{value:g} °{fu}",
            "to":     f"{result:.6g} °{tu}",
            "source": "Built-in converter",
        }

    # Linear family
    from_factor, from_fam = _find_factor(from_norm)
    to_factor,   to_fam   = _find_factor(to_norm)

    if from_factor is None:
        logger.warning("Unknown unit: %s", from_unit)
        return None
    if to_factor is None:
        logger.warning("Unknown unit: %s", to_unit)
        return None
    if from_fam is not to_fam:
        logger.warning("Unit family mismatch: %s vs %s", from_unit, to_unit)
        return None

    result = value * from_factor / to_factor
    return {
        "from":   f"{value:g} {from_unit}",
        "to":     f"{result:.6g} {to_unit}",
        "source": "Built-in converter",
    }


def _convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    """
    Input: value, from_unit ('C'|'F'|'K'), to_unit ('C'|'F'|'K')
    Output: converted value as float
    Details:
        Converts through Celsius as the intermediate unit. Raises ValueError
        for unknown unit codes.
    """
    _valid = {"C", "F", "K"}
    if from_unit not in _valid or to_unit not in _valid:
        raise ValueError(f"Unknown temperature unit: {from_unit!r} or {to_unit!r}")

    # → Celsius
    if from_unit == "C":
        celsius = value
    elif from_unit == "F":
        celsius = (value - 32) * 5 / 9
    else:  # K
        celsius = value - 273.15

    # Celsius → target
    if to_unit == "C":
        return celsius
    elif to_unit == "F":
        return celsius * 9 / 5 + 32
    else:  # K
        return celsius + 273.15


def build_unit_converter_card(q: str) -> tuple:
    """
    Input: q — raw search query string
    Output: (answer_card dict, ai_context str) or (None, None)
    Details:
        Entry point for the inline dispatcher. Detects, converts, and returns
        a structured answer_card and ai_context string.
    """
    query = detect_unit_query(q)
    if not query:
        return None, None

    result = convert_units(query["value"], query["from_unit"], query["to_unit"])
    if result is None:
        return None, None

    body = f'{result["from"]} = {result["to"]}'
    answer_card = {
        "type":   "unit_converter",
        "label":  "Unit Converter",
        "body":   body,
        "source": result["source"],
    }
    ai_context = f"Unit conversion: {body}"
    return answer_card, ai_context


if __name__ == "__main__":
    pass
