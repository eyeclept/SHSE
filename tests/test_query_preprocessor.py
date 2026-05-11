"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for flask_app/services/query_preprocessor.py.
    No live services required; synonym expansion uses injectable map.
"""
# Imports
import pytest

from flask_app.services.query_preprocessor import (
    expand_synonyms,
    normalize,
    strip_preamble,
    strip_stopwords,
)

# Globals
_SYNONYM_MAP = {
    "server": {"host", "machine", "node"},
    "host": {"server", "machine", "node"},
    "machine": {"server", "host", "node"},
    "node": {"server", "host", "machine"},
    "network": {"networking", "net"},
    "networking": {"network", "net"},
    "net": {"network", "networking"},
    "storage": {"disk", "drive", "volume"},
    "disk": {"storage", "drive", "volume"},
}


# Functions

# ── strip_preamble ────────────────────────────────────────────────────────────

def test_strip_preamble_please_search_for():
    """
    Input:  "please search for server config"
    Output: "server config"
    """
    assert strip_preamble("please search for server config") == "server config"


def test_strip_preamble_what_is():
    """
    Input:  "what is Docker"
    Output: "Docker"
    """
    assert strip_preamble("what is Docker") == "Docker"


def test_strip_preamble_find_me():
    """
    Input:  "find me network logs"
    Output: "network logs"
    """
    assert strip_preamble("find me network logs") == "network logs"


def test_strip_preamble_how_do_i():
    """
    Input:  "how do I configure nginx"
    Output: "configure nginx"
    """
    assert strip_preamble("how do I configure nginx") == "configure nginx"


def test_strip_preamble_tell_me_about():
    """
    Input:  "tell me about backups"
    Output: "backups"
    """
    assert strip_preamble("tell me about backups") == "backups"


def test_strip_preamble_plain_query_unchanged():
    """
    Input:  plain query with no preamble
    Output: same string
    """
    assert strip_preamble("server config") == "server config"
    assert strip_preamble("nginx configuration") == "nginx configuration"


def test_strip_preamble_does_not_empty_string():
    """
    Input:  preamble followed by single word
    Output: the single word (not empty)
    """
    result = strip_preamble("what is kubernetes")
    assert result == "kubernetes"
    assert result != ""


# ── normalize ─────────────────────────────────────────────────────────────────

def test_normalize_lowercases():
    """
    Input:  "NGINX Config"
    Output: "nginx config"
    """
    assert normalize("NGINX Config") == "nginx config"


def test_normalize_collapses_whitespace():
    """
    Input:  "  Hello,  World!  " (extra spaces and punctuation)
    Output: "hello world"
    """
    assert normalize("  Hello,  World!  ") == "hello world"


def test_normalize_strips_punctuation():
    """
    Input:  "nginx.conf (server block)"
    Output: string with no dots or parentheses
    """
    result = normalize("nginx.conf (server block)")
    assert "." not in result
    assert "(" not in result


def test_normalize_preserves_hyphens_and_apostrophes():
    """
    Input:  "it's a self-signed cert"
    Output: hyphens and apostrophes preserved in result
    """
    result = normalize("it's a self-signed cert")
    assert "-" in result
    assert "'" in result


def test_normalize_single_space():
    """
    Input:  "a   b   c" (multiple spaces between words)
    Output: "a b c"
    """
    assert normalize("a   b   c") == "a b c"


# ── strip_stopwords ───────────────────────────────────────────────────────────

def test_strip_stopwords_removes_the():
    """
    Input:  "the server is down"
    Output: "the" removed; "server" retained
    """
    result = strip_stopwords("the server is down")
    assert "the" not in result.split()
    assert "server" in result


def test_strip_stopwords_never_empties():
    """
    Input:  query composed entirely of stopwords
    Output: original string returned, not empty
    """
    query = "the a an is"
    result = strip_stopwords(query)
    assert result != ""


def test_strip_stopwords_plain_terms_unchanged():
    """
    Input:  "server config backup" (no stopwords)
    Output: all three terms present in result
    """
    result = strip_stopwords("server config backup")
    assert "server" in result
    assert "config" in result
    assert "backup" in result


# ── expand_synonyms ───────────────────────────────────────────────────────────

def test_expand_synonyms_adds_synonyms(monkeypatch):
    """
    Input:  "server config" with injected synonym map
    Output: result contains at least one synonym of "server"
    Details:
        Uses injectable synonym_map to avoid filesystem access in tests.
    """
    result = expand_synonyms("server config", synonym_map=_SYNONYM_MAP)
    assert "server" in result
    assert any(syn in result for syn in ("host", "machine", "node"))


def test_expand_synonyms_no_duplicates():
    """
    Input:  "server host" — both terms are synonyms of each other
    Output: neither 'server' nor 'host' is added twice
    """
    result = expand_synonyms("server host", synonym_map=_SYNONYM_MAP)
    words = result.split()
    assert words.count("server") == 1
    assert words.count("host") == 1


def test_expand_synonyms_empty_map_returns_unchanged():
    """
    Input:  "server config" with empty synonym map
    Output: "server config" unchanged
    """
    result = expand_synonyms("server config", synonym_map={})
    assert result == "server config"


def test_expand_synonyms_no_matching_term_unchanged():
    """
    Input:  "kubernetes pod" — no entries in synonym map
    Output: result starts with original query unchanged
    """
    result = expand_synonyms("kubernetes pod", synonym_map=_SYNONYM_MAP)
    assert result.startswith("kubernetes pod")


# ── integration: full pipeline ────────────────────────────────────────────────

def test_full_pipeline_preamble_query():
    """
    Input:  "please find me server information"
    Output: preprocessed string contains "server" (no preamble)
    """
    raw = "please find me server information"
    step1 = strip_preamble(raw)
    step2 = normalize(step1)
    step3 = strip_stopwords(step2)
    assert "server" in step3


def test_full_pipeline_plain_query_passes_through():
    """
    Input:  "server config" — no preamble, no stopwords
    Output: "server config" unchanged (no normalization change since already lower/no punct)
    """
    raw = "server config"
    step1 = strip_preamble(raw)
    step2 = normalize(step1)
    step3 = strip_stopwords(step2)
    assert step3 == "server config"
