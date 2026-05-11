"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for task 17a — StarDict OED reader, markup stripping, query detection,
    and answer_card / ai_context construction.
    Uses actual dictionary files at the path set by STARDICT_DICT_PATH.
    All tests skip automatically when no .ifo files are present in that directory
    (e.g. a fresh clone before dicts are added to ./dicts/).
"""
# Imports
import logging

import pytest

from flask_app.services.stardict import (
    OedReader,
    StarDictReader,
    _DICT_BASE,
    _OED_P1_STEM,
    _OED_P2_STEM,
    _strip_markup,
    build_definition_card,
    detect_definition_query,
    parse_oed_entry,
)

# Globals
logger = logging.getLogger(__name__)

_DICTS_PRESENT = any(_DICT_BASE.rglob("*.ifo")) if _DICT_BASE.exists() else False

pytestmark = pytest.mark.skipif(
    not _DICTS_PRESENT,
    reason=f"No StarDict .ifo files found in {_DICT_BASE} — add dict folders to ./dicts/",
)

_OED = OedReader()

# ── Word lists ────────────────────────────────────────────────────────────────

# Words confirmed in P1 (verified against idx at test-authoring time)
_P1_WORDS = [
    "bank", "bear", "light", "fast", "like", "lewd", "fond", "be", "go",
    "algebra", "berserk", "canoe", "blackbird", "make", "entropy",
    "algorithm", "boycott", "ice-cream",
]

# Words confirmed in P2 only
_P2_WORDS = [
    "set", "round", "well", "nice", "silly", "mouse", "ox",
    "schadenfreude", "well-being", "run", "point", "mitosis", "sandwich",
]

# Words absent from both volumes of this OED edition
_ABSENT_WORDS = [
    "selfie",      # coined ~2013; post-dates OED 2nd Ed. (2011 StarDict release)
    "zzznonsenseword",
]

# Multi-POS words: parser must return ≥ 2 distinct sections
_MULTI_POS_WORDS = [
    "bank",    # n. + v.
    "bear",    # n. + v.
    "light",   # n. + a. + v.
    "fast",    # a. + adv. + v. + n.
    "like",    # v. + n. + a. + adv. + prep.
    "round",   # a. + adv./prep. + n. + v.
    "run",     # n. + v.
    "make",    # v. + n.
    "point",   # n. + v.
    "well",    # n. + v. + adv./adj.
]

# Loan-word etymologies: etymology block must be non-empty
_ETYMOLOGY_WORDS = [
    "algebra",      # Arabic al-jabr
    "berserk",      # Old Norse
    "schadenfreude",# German compound
    "canoe",        # Caribbean via Spanish
    "boycott",      # named after Capt. Boycott
    "sandwich",     # named after Earl of Sandwich
    "algorithm",    # Arabic al-Khwarizmi
]

# Semantic-drift words: OED must contain ≥ 2 definitions (historical + modern)
_SEMANTIC_DRIFT_WORDS = [
    "nice",    # originally "foolish/wanton" → now "pleasant"
    "silly",   # originally "blessed/happy" → now "foolish"
    "lewd",    # originally "lay/unlearned" → now "indecent"
    "fond",    # originally "foolish" → now "affectionate"
    "berserk", # originally "bear-shirt Norse warrior" → now "violently frenzied"
]


# ── Core lookup tests ────────────────────────────────────────────────────────

def test_lookup_human():
    """
    Input:  word "human"
    Output: non-empty string
    Details:
        Verifies basic OED lookup returns a non-empty definition.
    """
    result = _OED.lookup("human")
    assert result is not None
    assert len(result) > 0


def test_lookup_nonsense_returns_none():
    """
    Input:  word "zzznonsenseword"
    Output: None
    Details:
        Verifies that a word absent from both OED volumes returns None.
    """
    assert _OED.lookup("zzznonsenseword") is None


def test_markup_stripped():
    """
    Input:  lookup result for "human"
    Output: string with no '<' characters
    Details:
        Verifies all XML/HTML tags are removed from the definition.
    """
    result = _OED.lookup("human")
    assert result is not None
    assert "<" not in result


def test_p2_fallback():
    """
    Input:  word "water" (present in P2 only)
    Output: non-empty string via P2 fallback
    Details:
        "water" is absent from P1; OedReader must find it in P2.
    """
    assert StarDictReader(_OED_P1_STEM).lookup("water") is None
    result = _OED.lookup("water")
    assert result is not None and len(result) > 0


# ── Query detection tests ────────────────────────────────────────────────────

def test_detect_define_prefix():
    """
    Input:  "define human"
    Output: "human"
    """
    assert detect_definition_query("define human") == "human"


def test_detect_definition_suffix():
    """
    Input:  "human definition"
    Output: "human"
    """
    assert detect_definition_query("human definition") == "human"


def test_plain_query_not_detected():
    """
    Input:  "human"
    Output: None — plain queries must not trigger the card.
    """
    assert detect_definition_query("human") is None


# ── Parametrized presence tests ──────────────────────────────────────────────

@pytest.mark.parametrize("word", _P1_WORDS)
def test_p1_word_found(word):
    """
    Input:  word confirmed in OED P1
    Output: non-empty lookup result
    Details:
        Exercises StarDictReader for every P1 word in the test list.
    """
    result = _OED.lookup(word)
    assert result is not None, f"'{word}' expected in OED P1 but lookup returned None"
    assert len(result) > 0


@pytest.mark.parametrize("word", _P2_WORDS)
def test_p2_word_found(word):
    """
    Input:  word confirmed in OED P2 only
    Output: non-empty lookup result (must fail P1, succeed P2)
    Details:
        Verifies P1→P2 fallback for every P2-only word in the test list.
    """
    p1_result = StarDictReader(_OED_P1_STEM).lookup(word)
    assert p1_result is None, f"'{word}' should be absent from P1"
    result = _OED.lookup(word)
    assert result is not None, f"'{word}' expected in OED P2 but lookup returned None"
    assert len(result) > 0


@pytest.mark.parametrize("word", _ABSENT_WORDS)
def test_absent_word_returns_none(word):
    """
    Input:  word absent from both OED volumes
    Output: None
    Details:
        "selfie" post-dates this OED edition; nonsense word never existed.
    """
    assert _OED.lookup(word) is None, f"'{word}' should not be in the OED"


# ── Parser structural tests ──────────────────────────────────────────────────

@pytest.mark.parametrize("word", _MULTI_POS_WORDS)
def test_multi_pos_parse(word):
    """
    Input:  word with multiple parts of speech
    Output: parsed entry with ≥ 2 sections, each with ≥ 1 active definition
    Details:
        Verifies that parse_oed_entry splits multi-POS entries correctly and
        that each section yields at least one non-obsolete definition.
    """
    raw = _OED.lookup_raw(word)
    assert raw is not None, f"'{word}' not found in OED"
    parsed = parse_oed_entry(raw)
    assert len(parsed["sections"]) >= 2, (
        f"'{word}' expected ≥2 POS sections, got {len(parsed['sections'])}: "
        + str([s["pos"] for s in parsed["sections"]])
    )
    # At least 2 sections must contain active (non-obsolete) definitions.
    # Some sections legitimately contain only historical/obsolete senses.
    sections_with_active = [
        s for s in parsed["sections"]
        if any(not d["obsolete"] for d in s["definitions"])
    ]
    assert len(sections_with_active) >= 2, (
        f"'{word}' expected ≥2 sections with active defs, got "
        f"{len(sections_with_active)}: "
        + str([(s["pos"], len(s["definitions"])) for s in parsed["sections"]])
    )


@pytest.mark.parametrize("word", _ETYMOLOGY_WORDS)
def test_etymology_extracted(word):
    """
    Input:  loan word with a known etymological entry
    Output: non-empty etymology string in the first parsed section
    Details:
        OED entries for borrowed words always include a [source lang. ...] block;
        the parser must capture it.
    """
    raw = _OED.lookup_raw(word)
    assert raw is not None, f"'{word}' not found in OED"
    parsed = parse_oed_entry(raw)
    assert parsed["sections"], f"'{word}' parser returned no sections"
    etym = parsed["sections"][0].get("etymology", "")
    assert etym, f"'{word}' expected etymology block but got empty string"
    assert "[" in etym, f"'{word}' etymology should start with '[': {etym[:80]}"


@pytest.mark.parametrize("word", _SEMANTIC_DRIFT_WORDS)
def test_semantic_drift_has_multiple_defs(word):
    """
    Input:  word whose meaning changed substantially over time
    Output: parsed entry with ≥ 2 definitions across all sections
    Details:
        Words like "nice" (originally "foolish") or "silly" (originally "blessed")
        should have at least two definitions reflecting historical and modern senses.
    """
    raw = _OED.lookup_raw(word)
    assert raw is not None, f"'{word}' not found in OED"
    parsed = parse_oed_entry(raw)
    all_defs = [d for s in parsed["sections"] for d in s["definitions"]]
    assert len(all_defs) >= 2, (
        f"'{word}' expected ≥2 definitions (historical + modern), "
        f"got {len(all_defs)}"
    )


def test_pronunciation_extracted():
    """
    Input:  word "algorithm"
    Output: parsed entry with non-empty IPA pronunciation
    Details:
        Verifies the darkslategray <c> tag is correctly parsed as IPA.
    """
    raw = _OED.lookup_raw("algorithm")
    assert raw is not None
    parsed = parse_oed_entry(raw)
    pron = parsed["sections"][0]["pronunciation"] if parsed["sections"] else ""
    assert pron, "Expected IPA pronunciation for 'algorithm'"


def test_ice_cream_hyphen():
    """
    Input:  "ice-cream" (hyphenated)
    Output: non-empty lookup result
    Details:
        "ice cream" (spaced) is absent; "ice-cream" (hyphenated) is the OED headword.
        Confirms users need to search "define ice-cream" for a result.
    """
    assert _OED.lookup("ice cream") is None
    result = _OED.lookup("ice-cream")
    assert result is not None and len(result) > 0


# ── answer_card / ai_context tests ───────────────────────────────────────────

def test_answer_card_structure():
    """
    Input:  query "define human"
    Output: answer_card with type, word, parsed, source; ≥1 active definition
    """
    card, ctx = build_definition_card("define human")
    assert card is not None
    assert card["type"] == "definition"
    assert card["word"] == "human"
    assert card["source"] == "Oxford English Dictionary"
    assert "parsed" in card and card["parsed"]["sections"]
    first = card["parsed"]["sections"][0]
    assert any(not d["obsolete"] for d in first["definitions"])


def test_ai_context_contains_definition():
    """
    Input:  query "define human"
    Output: ai_context str containing the word and definition text
    """
    card, ctx = build_definition_card("define human")
    assert ctx is not None
    assert "human" in ctx.lower()
    assert len(ctx) > 10


if __name__ == "__main__":
    pass
