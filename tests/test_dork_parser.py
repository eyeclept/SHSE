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
    parsed = parse_dorks("site:kiwix human")
    assert parsed["filters"]["site"] == "kiwix"
    assert "human" in parsed["plain_terms"]
    assert has_dorks(parsed) is True


def test_intitle_operator_parsed():
    parsed = parse_dorks("intitle:anatomy")
    assert parsed["filters"]["intitle"] == "anatomy"
    assert parsed["plain_terms"] == []
    assert has_dorks(parsed) is True


def test_inurl_operator_parsed():
    parsed = parse_dorks("inurl:/A/ medicine")
    assert parsed["filters"]["inurl"] == "/A/"
    assert "medicine" in parsed["plain_terms"]


def test_filetype_operator_parsed():
    parsed = parse_dorks("filetype:html tutorial")
    assert parsed["filters"]["filetype"] == "html"
    assert "tutorial" in parsed["plain_terms"]


def test_exact_phrase_parsed():
    parsed = parse_dorks('"human anatomy"')
    assert parsed["must_phrases"] == ["human anatomy"]
    assert parsed["plain_terms"] == []
    assert has_dorks(parsed) is True


def test_exclude_term_parsed():
    parsed = parse_dorks("human -animal")
    assert "animal" in parsed["exclude_terms"]
    assert "human" in parsed["plain_terms"]
    assert has_dorks(parsed) is True


def test_combined_multiple_operators():
    parsed = parse_dorks('site:kiwix "cell biology" -virus intitle:cell')
    assert parsed["filters"]["site"] == "kiwix"
    assert parsed["filters"]["intitle"] == "cell"
    assert parsed["must_phrases"] == ["cell biology"]
    assert "virus" in parsed["exclude_terms"]
    assert has_dorks(parsed) is True


def test_plain_query_no_operators():
    parsed = parse_dorks("mitochondria cell biology")
    assert parsed["filters"] == {"site": None, "inurl": None, "intitle": None, "filetype": None}
    assert parsed["must_phrases"] == []
    assert parsed["exclude_terms"] == []
    assert parsed["plain_terms"] == ["mitochondria", "cell", "biology"]
    assert has_dorks(parsed) is False


def test_empty_query():
    parsed = parse_dorks("")
    assert has_dorks(parsed) is False
    assert parsed["plain_terms"] == []


def test_multiple_site_uses_last():
    # Later occurrence overwrites earlier (last wins)
    parsed = parse_dorks("site:kiwix site:openzim")
    assert parsed["filters"]["site"] == "openzim"


def test_quoted_phrase_with_plain_terms():
    parsed = parse_dorks('python "machine learning" tutorial')
    assert "machine learning" in parsed["must_phrases"]
    assert "python" in parsed["plain_terms"]
    assert "tutorial" in parsed["plain_terms"]
