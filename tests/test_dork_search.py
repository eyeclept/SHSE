"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for bm25_body_with_dorks() in flask_app/services/search.py.
    Verifies that dork operators produce correct OpenSearch DSL.
    No live services required — inspects the returned body dict.
"""
import pytest
from flask_app.services.search import bm25_body, bm25_body_with_dorks


def _must_clauses(body):
    return body["query"]["bool"].get("must", [])


def _filter_clauses(body):
    return body["query"]["bool"].get("filter", [])


def _must_not_clauses(body):
    return body["query"]["bool"].get("must_not", [])


def test_plain_query_falls_back_to_multimatch():
    """
    Input:  "mitochondria cell biology" (no dork operators)
    Output: body["query"] uses multi_match (plain BM25 path)
    """
    body = bm25_body_with_dorks("mitochondria cell biology")
    assert "multi_match" in body["query"]


def test_site_produces_wildcard_url_filter():
    """
    Input:  "site:kiwix human"
    Output: filter clause contains wildcard on url field matching "*kiwix*"
    """
    body = bm25_body_with_dorks("site:kiwix human")
    filters = _filter_clauses(body)
    assert any(
        "wildcard" in f and "*kiwix*" in f["wildcard"]["url"]["value"]
        for f in filters
    ), f"Expected wildcard url filter for 'kiwix', got: {filters}"


def test_inurl_produces_wildcard_url_filter():
    """
    Input:  "inurl:/A/ cell"
    Output: filter clause contains wildcard on url field matching "*/ A/*"
    """
    body = bm25_body_with_dorks("inurl:/A/ cell")
    filters = _filter_clauses(body)
    assert any(
        "wildcard" in f and "*/A/*" in f["wildcard"]["url"]["value"]
        for f in filters
    )


def test_intitle_produces_match_filter():
    """
    Input:  "intitle:anatomy"
    Output: filter clause contains match on title field with value "anatomy"
    """
    body = bm25_body_with_dorks("intitle:anatomy")
    filters = _filter_clauses(body)
    assert any("match" in f and f["match"].get("title") == "anatomy" for f in filters)


def test_filetype_produces_term_filter():
    """
    Input:  "filetype:html tutorial"
    Output: filter clause contains term on content_type field with value "html"
    """
    body = bm25_body_with_dorks("filetype:html tutorial")
    filters = _filter_clauses(body)
    assert any("term" in f and f["term"].get("content_type") == "html" for f in filters)


def test_exact_phrase_produces_match_phrase():
    """
    Input:  '"human anatomy"' (double-quoted phrase)
    Output: must clause contains match_phrase on text field with value "human anatomy"
    """
    body = bm25_body_with_dorks('"human anatomy"')
    must = _must_clauses(body)
    assert any("match_phrase" in c and c["match_phrase"].get("text") == "human anatomy" for c in must)


def test_exclude_term_in_must_not():
    """
    Input:  "human -animal"
    Output: must_not clause contains multi_match with query "animal"
    """
    body = bm25_body_with_dorks("human -animal")
    must_not = _must_not_clauses(body)
    assert any(
        "multi_match" in c and c["multi_match"]["query"] == "animal"
        for c in must_not
    )


def test_combined_operators_correct_bool_dsl():
    """
    Input:  'site:kiwix "cell biology" -virus'
    Output: site in filters, phrase in must, virus in must_not — all correct simultaneously
    """
    body = bm25_body_with_dorks('site:kiwix "cell biology" -virus')
    filters = _filter_clauses(body)
    must = _must_clauses(body)
    must_not = _must_not_clauses(body)

    assert any("wildcard" in f for f in filters), "site: should produce filter"
    assert any("match_phrase" in c for c in must), "phrase should be in must"
    assert any("multi_match" in c and c["multi_match"]["query"] == "virus" for c in must_not)


def test_no_operators_plain_terms_go_to_multimatch():
    """
    Input:  "quantum physics" (plain terms, no operators)
    Output: multi_match query with query string "quantum physics"
    """
    body = bm25_body_with_dorks("quantum physics")
    assert "multi_match" in body["query"]
    assert body["query"]["multi_match"]["query"] == "quantum physics"


def test_pagination_respected():
    """
    Input:  page=3, page_size=5
    Output: body["from"]==10, body["size"]==5
    """
    body = bm25_body_with_dorks("site:kiwix test", page=3, page_size=5)
    assert body["from"] == 10
    assert body["size"] == 5


def test_highlight_tags_propagated():
    """
    Input:  highlight_tags=("<em>", "</em>")
    Output: body["highlight"]["pre_tags"]==["<em>"], post_tags==["</em>"]
    """
    body = bm25_body_with_dorks("site:kiwix test", highlight_tags=("<em>", "</em>"))
    assert body["highlight"]["pre_tags"] == ["<em>"]
    assert body["highlight"]["post_tags"] == ["</em>"]


def test_aggregation_always_present():
    """
    Input:  any query
    Output: body contains "aggs" key with "by_service" bucket aggregation
    """
    body = bm25_body_with_dorks("site:kiwix test")
    assert "aggs" in body
    assert "by_service" in body["aggs"]
