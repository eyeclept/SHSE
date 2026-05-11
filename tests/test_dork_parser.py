"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Unit tests for flask_app/services/dork_parser.py.
    No live services required — pure parsing logic.
"""
import pytest
from flask_app.services.dork_parser import parse_dorks, has_dorks


def test_site_operator_parsed():
    """
    Input:  "site:kiwix human"
    Output: filters["site"]=="kiwix", "human" in plain_terms, has_dorks True
    """
    parsed = parse_dorks("site:kiwix human")
    assert parsed["filters"]["site"] == "kiwix"
    assert "human" in parsed["plain_terms"]
    assert has_dorks(parsed) is True


def test_intitle_operator_parsed():
    """
    Input:  "intitle:anatomy"
    Output: filters["intitle"]=="anatomy", empty plain_terms, has_dorks True
    """
    parsed = parse_dorks("intitle:anatomy")
    assert parsed["filters"]["intitle"] == "anatomy"
    assert parsed["plain_terms"] == []
    assert has_dorks(parsed) is True


def test_inurl_operator_parsed():
    """
    Input:  "inurl:/A/ medicine"
    Output: filters["inurl"]=="/A/", "medicine" in plain_terms
    """
    parsed = parse_dorks("inurl:/A/ medicine")
    assert parsed["filters"]["inurl"] == "/A/"
    assert "medicine" in parsed["plain_terms"]


def test_filetype_operator_parsed():
    """
    Input:  "filetype:html tutorial"
    Output: filters["filetype"]=="html", "tutorial" in plain_terms
    """
    parsed = parse_dorks("filetype:html tutorial")
    assert parsed["filters"]["filetype"] == "html"
    assert "tutorial" in parsed["plain_terms"]


def test_exact_phrase_parsed():
    """
    Input:  '"human anatomy"' (double-quoted phrase)
    Output: must_phrases==["human anatomy"], empty plain_terms, has_dorks True
    """
    parsed = parse_dorks('"human anatomy"')
    assert parsed["must_phrases"] == ["human anatomy"]
    assert parsed["plain_terms"] == []
    assert has_dorks(parsed) is True


def test_exclude_term_parsed():
    """
    Input:  "human -animal" (minus-prefixed exclusion)
    Output: "animal" in exclude_terms, "human" in plain_terms, has_dorks True
    """
    parsed = parse_dorks("human -animal")
    assert "animal" in parsed["exclude_terms"]
    assert "human" in parsed["plain_terms"]
    assert has_dorks(parsed) is True


def test_combined_multiple_operators():
    """
    Input:  'site:kiwix "cell biology" -virus intitle:cell'
    Output: all four operator types parsed correctly in one query
    """
    parsed = parse_dorks('site:kiwix "cell biology" -virus intitle:cell')
    assert parsed["filters"]["site"] == "kiwix"
    assert parsed["filters"]["intitle"] == "cell"
    assert parsed["must_phrases"] == ["cell biology"]
    assert "virus" in parsed["exclude_terms"]
    assert has_dorks(parsed) is True


def test_plain_query_no_operators():
    """
    Input:  "mitochondria cell biology" (no dork operators)
    Output: all filters None, empty phrases/excludes, terms list populated, has_dorks False
    """
    parsed = parse_dorks("mitochondria cell biology")
    assert parsed["filters"] == {"site": None, "inurl": None, "intitle": None, "filetype": None}
    assert parsed["must_phrases"] == []
    assert parsed["exclude_terms"] == []
    assert parsed["plain_terms"] == ["mitochondria", "cell", "biology"]
    assert has_dorks(parsed) is False


def test_empty_query():
    """
    Input:  "" (empty string)
    Output: has_dorks False, empty plain_terms
    """
    parsed = parse_dorks("")
    assert has_dorks(parsed) is False
    assert parsed["plain_terms"] == []


def test_multiple_site_uses_last():
    """
    Input:  "site:kiwix site:openzim" (duplicate operator key)
    Output: filters["site"]=="openzim" (last value wins)
    """
    parsed = parse_dorks("site:kiwix site:openzim")
    assert parsed["filters"]["site"] == "openzim"


def test_quoted_phrase_with_plain_terms():
    """
    Input:  'python "machine learning" tutorial'
    Output: must_phrases contains "machine learning"; plain_terms has "python" and "tutorial"
    """
    parsed = parse_dorks('python "machine learning" tutorial')
    assert "machine learning" in parsed["must_phrases"]
    assert "python" in parsed["plain_terms"]
    assert "tutorial" in parsed["plain_terms"]
