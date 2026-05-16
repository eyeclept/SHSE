"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Parse Google-style search operators from a raw query string.

Supported operators:
    site:host       — filter to docs whose URL contains 'host'
    inurl:path      — filter to docs whose URL contains 'path'
    intitle:word    — match only in the title field
    filetype:ext    — filter by content_type field
    "exact phrase"  — exact phrase match
    -term           — exclude docs containing 'term'
"""
# Imports
import logging
import re

# Globals
logger = logging.getLogger(__name__)

# Matches (in order): operator:value | "quoted phrase" | -exclude | plain_token
_TOKEN_RE = re.compile(
    r'(site|inurl|intitle|filetype):(\S+)'
    r'|"([^"]*)"'
    r'|-(\S+)'
    r'|(\S+)'
)


def parse_dorks(raw_q: str) -> dict:
    """
    Input:
        raw_q - str, raw query string possibly containing dork operators
    Output:
        dict with keys:
            filters       - dict {site, inurl, intitle, filetype} (str|None each)
            must_phrases  - list[str], exact-phrase matches
            exclude_terms - list[str], terms to exclude
            plain_terms   - list[str], plain search terms
    Details:
        Tokenises the query left-to-right. Operator values may not contain
        whitespace. Quoted phrases may contain spaces. Unrecognised tokens
        are treated as plain terms.
    """
    filters = {"site": None, "inurl": None, "intitle": None, "filetype": None}
    must_phrases: list[str] = []
    exclude_terms: list[str] = []
    plain_terms: list[str] = []

    for m in _TOKEN_RE.finditer(raw_q):
        op, op_val, phrase, exclude, plain = m.groups()
        if op is not None:
            if op in filters:
                filters[op] = op_val
        elif phrase is not None:
            must_phrases.append(phrase)
        elif exclude is not None:
            exclude_terms.append(exclude)
        elif plain is not None:
            plain_terms.append(plain)

    return {
        "filters": filters,
        "must_phrases": must_phrases,
        "exclude_terms": exclude_terms,
        "plain_terms": plain_terms,
    }


# Functions
def has_dorks(parsed: dict) -> bool:
    """
    Input:  parsed - dict returned by parse_dorks
    Output: bool — True if any dork operators were found in the query
    Details:
        Returns True when at least one filter key is non-None, or there are
        phrase or exclude terms. Plain-term-only queries return False.
    """
    return (
        any(v is not None for v in parsed["filters"].values())
        or bool(parsed["must_phrases"])
        or bool(parsed["exclude_terms"])
    )


if __name__ == "__main__":
    pass
