"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Query preprocessing pipeline. Cleans and enriches user queries before
    they reach the search backend.

    Pipeline order (each function is independently callable):
        strip_preamble  — remove leading natural-language filler
        normalize       — lowercase, collapse whitespace, strip punctuation
        strip_stopwords — remove common function words
        expand_synonyms — add domain synonyms from config/synonyms.yaml

    All functions accept and return plain str. No external dependencies;
    uses stdlib re and yaml (already in requirements.txt).
"""
# Imports
import logging
import os
import re

import yaml

# Globals
logger = logging.getLogger(__name__)

_CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config")
_SYNONYMS_PATH = os.path.join(_CONFIG_DIR, "synonyms.yaml")

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has",
    "have", "how", "i", "if", "in", "into", "is", "it", "its", "may",
    "might", "most", "no", "not", "of", "on", "or", "other", "so",
    "some", "such", "than", "that", "the", "their", "them", "then",
    "these", "they", "this", "those", "to", "was", "were", "what",
    "when", "where", "which", "who", "will", "with", "would",
}

_PREAMBLE_RE = re.compile(
    r"^(?:"
    r"please\s+search\s+for\s+|"
    r"can\s+you\s+(?:please\s+)?(?:search\s+for|find|look\s+up)\s+|"
    r"find\s+me\s+|"
    r"search\s+for\s+|"
    r"look\s+up\s+|"
    r"what\s+(?:is|are)\s+|"
    r"who\s+(?:is|are)\s+|"
    r"tell\s+me\s+(?:about|how|what|who|where|when)\s+|"
    r"show\s+me\s+(?:(?:how|what|where|who|when)\s+)?|"
    r"give\s+me\s+(?:info(?:rmation)?\s+(?:about|on)\s+)?|"
    r"i\s+want\s+to\s+(?:know\s+(?:about|how)\s+)?|"
    r"how\s+(?:do\s+i|to)\s+|"
    r"help\s+me\s+(?:find|understand|with)\s+"
    r")",
    re.IGNORECASE,
)

_NORMALIZE_STRIP_RE = re.compile(r"[^\w\s\-\']", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")

_synonym_cache = None


# Functions
def strip_preamble(query: str) -> str:
    """
    Input:  query — raw user query string
    Output: query with leading natural-language preamble removed
    Details:
        Applies a single regex pass anchored at the start of the string.
        Only the longest matching prefix is stripped; the rest is returned
        unchanged. If no preamble is found the input is returned as-is.
    """
    stripped = _PREAMBLE_RE.sub("", query.lstrip(), count=1).strip()
    return stripped if stripped else query.strip()


def normalize(query: str) -> str:
    """
    Input:  query — string to normalise
    Output: lowercased, single-spaced, punctuation-stripped string
    Details:
        Lowercases the entire string; strips characters that are neither
        alphanumeric, space, hyphen, nor apostrophe (Unicode-aware word
        chars are preserved via \\w); collapses runs of whitespace to a
        single space; strips leading/trailing whitespace.
    """
    lowered = query.lower()
    stripped = _NORMALIZE_STRIP_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", stripped).strip()


def strip_stopwords(query: str) -> str:
    """
    Input:  query — normalised query string
    Output: query with stopword tokens removed
    Details:
        Splits on whitespace, removes tokens present in STOPWORDS, and
        rejoins. If removing stopwords would leave an empty string the
        original normalised form is returned unchanged so callers always
        receive a non-empty query.
    """
    tokens = query.split()
    filtered = [t for t in tokens if t.lower() not in STOPWORDS]
    return " ".join(filtered) if filtered else query


def _load_synonyms() -> dict:
    """
    Input:  None
    Output: dict mapping each term to a set of synonym terms
    Details:
        Reads config/synonyms.yaml once and caches the result. The YAML
        file contains a list of lists; each inner list is a group of
        equivalent terms. The returned dict has every term in a group
        mapped to the set of other terms in that group.
    """
    global _synonym_cache
    if _synonym_cache is not None:
        return _synonym_cache

    mapping: dict = {}
    try:
        with open(_SYNONYMS_PATH, encoding="utf-8") as fh:
            groups = yaml.safe_load(fh) or []
        for group in groups:
            terms = [str(t).lower() for t in group if t]
            for term in terms:
                others = set(terms) - {term}
                if term in mapping:
                    mapping[term].update(others)
                else:
                    mapping[term] = set(others)
    except Exception:
        logger.warning("Failed to load synonyms from %s", _SYNONYMS_PATH, exc_info=True)
    _synonym_cache = mapping
    return mapping


def expand_synonyms(query: str, synonym_map: dict | None = None) -> str:
    """
    Input:
        query       — preprocessed query string
        synonym_map — optional dict{term: set{synonyms}} for test injection;
                      when None the config/synonyms.yaml groups are used
    Output: query string with synonym terms appended (space-separated)
    Details:
        For each token in the query, looks up synonyms and appends any that
        are not already present in the query. Tokens are compared
        case-insensitively. Original token order and casing are preserved;
        synonyms are appended lowercased. When the synonym map is empty
        (file absent or unreadable) the input is returned unchanged.
    """
    mapping = synonym_map if synonym_map is not None else _load_synonyms()
    if not mapping:
        return query

    tokens = query.split()
    query_words = {t.lower() for t in tokens}
    extras: list[str] = []
    for token in tokens:
        for syn in sorted(mapping.get(token.lower(), [])):
            if syn not in query_words:
                extras.append(syn)
                query_words.add(syn)

    if extras:
        return query + " " + " ".join(extras)
    return query


if __name__ == "__main__":
    pass
