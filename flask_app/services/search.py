"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Composite search service. Combines BM25 and semantic (vector) retrieval
    and optionally generates an AI summary via the LLM API.
    Used by both the HTML search route and the JSON API endpoint.
"""
# Imports
import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed

# Globals
logger = logging.getLogger(__name__)
_INDEX_NAME = "shse_pages"
_PAGE_SIZE = 10
_VECTOR_K = 10
_RRF_K = 60


# Functions
def bm25_body(q, page=1, page_size=_PAGE_SIZE, highlight_tags=None, filter_services=None, sort="relevance"):
    """
    Input:
        q              - str, search query
        page           - int, 1-indexed page number
        page_size      - int, results per page
        highlight_tags - tuple (pre, post) for highlight tags; defaults to plain text
        filter_services - list[str] | None, service_nickname values to filter to
        sort           - str, one of 'relevance' (default), 'date_desc', 'date_asc'
    Output:
        dict — OpenSearch request body for a multi_match BM25 query
    Details:
        Uses multi_match best_fields across `text` and `title` (title boosted 2x).
        fuzziness=AUTO provides 1–2 edit distance tolerance for typos.
        prefix_length=1 prevents fuzzing the first character of each term so
        very short queries don't match everything.
        When filter_services is non-empty, wraps in a bool query with a terms filter.
        When sort is date_desc/date_asc, adds an explicit sort block.
    """
    pre_tag, post_tag = highlight_tags or ("", "")
    match_clause = {
        "multi_match": {
            "query": q,
            "fields": ["title^2", "text"],
            "type": "best_fields",
            "fuzziness": "AUTO",
            "prefix_length": 1,
        }
    }
    if filter_services:
        query = {
            "bool": {
                "must": match_clause,
                "filter": [{"terms": {"service_nickname": list(filter_services)}}],
            }
        }
    else:
        query = match_clause

    body = {
        "from": (page - 1) * page_size,
        "size": page_size,
        "query": query,
        "highlight": {
            "fields": {"text": {}, "title": {}},
            "pre_tags": [pre_tag],
            "post_tags": [post_tag],
            "number_of_fragments": 2,
            "fragment_size": 180,
        },
        "aggs": {
            "by_service": {"terms": {"field": "service_nickname", "size": 20}},
        },
    }
    if sort == "date_desc":
        body["sort"] = [{"crawled_at": "desc"}, "_score"]
    elif sort == "date_asc":
        body["sort"] = [{"crawled_at": "asc"}, "_score"]
    return body



def bm25_body_with_dorks(raw_q, page=1, page_size=_PAGE_SIZE, highlight_tags=None, filter_services=None, sort="relevance"):
    """
    Input:
        raw_q           - str, raw query string (may contain dork operators)
        page            - int, 1-indexed page number
        page_size       - int, results per page
        highlight_tags  - tuple (pre, post) for highlight tags
        filter_services - list[str] | None, service_nickname values to filter to
        sort            - str, one of 'relevance' (default), 'date_desc', 'date_asc'
    Output:
        dict — OpenSearch request body using bool query DSL
    Details:
        Parses dork operators from raw_q. When no operators are present,
        falls back to bm25_body() multi-match behaviour (transparent).
        Operators map to:
            site:/inurl: → wildcard filter on `url`
            intitle:     → match filter on `title`
            filetype:    → term filter on `content_type`
            "phrase"     → match_phrase clause in must
            -term        → multi_match clause in must_not
        filter_services and sort are passed through in both code paths.
    """
    from flask_app.services.dork_parser import parse_dorks, has_dorks

    parsed = parse_dorks(raw_q)
    if not has_dorks(parsed):
        plain_q = " ".join(parsed["plain_terms"]) or raw_q
        return bm25_body(plain_q, page=page, page_size=page_size, highlight_tags=highlight_tags,
                         filter_services=filter_services, sort=sort)

    pre_tag, post_tag = highlight_tags or ("", "")
    must = []
    filter_clauses = []
    must_not = []

    plain_q = " ".join(parsed["plain_terms"])
    if plain_q:
        must.append({
            "multi_match": {
                "query": plain_q,
                "fields": ["title^2", "text"],
                "type": "best_fields",
                "fuzziness": "AUTO",
                "prefix_length": 1,
            }
        })

    for phrase in parsed["must_phrases"]:
        must.append({"match_phrase": {"text": phrase}})

    f = parsed["filters"]
    if f["site"]:
        filter_clauses.append({"wildcard": {"url": {"value": f"*{f['site']}*"}}})
    if f["inurl"]:
        filter_clauses.append({"wildcard": {"url": {"value": f"*{f['inurl']}*"}}})
    if f["intitle"]:
        filter_clauses.append({"match": {"title": f["intitle"]}})
    if f["filetype"]:
        filter_clauses.append({"term": {"content_type": f["filetype"]}})
    if filter_services:
        filter_clauses.append({"terms": {"service_nickname": list(filter_services)}})

    for term in parsed["exclude_terms"]:
        must_not.append({"multi_match": {"query": term, "fields": ["title", "text"]}})

    bool_q: dict = {"must": must if must else [{"match_all": {}}]}
    if filter_clauses:
        bool_q["filter"] = filter_clauses
    if must_not:
        bool_q["must_not"] = must_not

    body = {
        "from": (page - 1) * page_size,
        "size": page_size,
        "query": {"bool": bool_q},
        "highlight": {
            "fields": {"text": {}, "title": {}},
            "pre_tags": [pre_tag],
            "post_tags": [post_tag],
            "number_of_fragments": 2,
            "fragment_size": 180,
        },
        "aggs": {
            "by_service": {"terms": {"field": "service_nickname", "size": 20}},
        },
    }
    if sort == "date_desc":
        body["sort"] = [{"crawled_at": "desc"}, "_score"]
    elif sort == "date_asc":
        body["sort"] = [{"crawled_at": "asc"}, "_score"]
    return body


_STOP_WORDS = {
    "the", "a", "an", "in", "of", "for", "to", "and", "or", "is", "are",
    "was", "were", "be", "been", "it", "its", "this", "that", "these",
    "those", "at", "by", "from", "with", "as", "on", "into", "about",
    "than", "also", "but", "not", "no", "so", "if", "has", "have", "had",
    "do", "does", "did", "will", "would", "can", "could", "may", "might",
    "their", "they", "them", "which", "who", "what", "when", "where",
    "how", "all", "one", "two", "more", "most", "such", "been", "its",
    "other", "many", "some", "used", "known", "well", "often", "also",
    "first", "time", "human", "humans",
}


def _keyword_chips(vector_hits, query, max_chips=6):
    """
    Input:
        vector_hits - list of vector search result dicts with 'snippet' keys
        query       - str, original search query
        max_chips   - int, maximum chips to return
    Output:
        list[str] — Google-style suggestions formed as "{query} {keyword}"
    Details:
        Extracts significant words (len >= 5) from the text snippets of vector
        hits. Excludes stop words and words already in the query. For single-word
        queries, prepends the query to form natural phrase suggestions.
        No external calls — uses data already fetched by vector search.
    """
    query_words = {w.lower().strip(".,;:()[]\"'") for w in query.split()}
    counts = {}
    for h in vector_hits:
        for raw in h.get("snippet", "").split():
            w = raw.strip(".,;:()[]\"'()-").lower()
            if len(w) >= 5 and w not in _STOP_WORDS and w not in query_words:
                counts[w] = counts.get(w, 0) + 1

    top_words = [w for w, _ in sorted(counts.items(), key=lambda x: -x[1])]

    if len(query.split()) == 1:
        return [f"{query} {w}" for w in top_words[:max_chips]]
    return top_words[:max_chips]


def _dummy_vector_search(q, os_client):
    """
    Input:  q — search query; os_client — OpenSearch client
    Output: empty list
    Details:
        Placeholder called by get_vector_hits when the embedding model is
        unavailable. Returns no results so the semantic rail degrades cleanly.
        TODO (Epic 18c): replace with a CPU-based embedding fallback so the
        semantic rail still returns real vector results when the GPU/API
        embedding model is down.
    """
    return []


def get_vector_hits(q, os_client=None, llm_session=None):
    """
    Input:
        q           - str, search query to embed and search
        os_client   - optional OpenSearch client (injectable for tests)
        llm_session - optional requests.Session for LLM API (injectable for tests)
    Output:
        tuple (hits, embedding_available) where:
            hits               - list[dict] each with score, service, url, title,
                                 snippet (200 chars for display), context (500 chars
                                 for AI summary)
            embedding_available - bool, False when embedding model was unreachable
    Details:
        Embeds the query and runs a k-NN vector search. Two-tier embedding:
        1. LLM API (get_embedding) — fast, GPU-backed.
        2. CPU fallback (get_cpu_embedding, sentence-transformers) — slower but
           produces compatible 768-d vectors so vector search remains accurate.
        Falls back to _dummy_vector_search (returns []) only when both fail.
        Returns embedding_available=True whenever real vector hits are returned
        (regardless of which embedding tier was used).
    """
    from flask_app.services.llm import get_embedding, get_cpu_embedding
    from flask_app.services.opensearch import vector_search, get_client

    client = os_client or get_client()

    embedding = get_embedding(q, session=llm_session)
    if embedding is None:
        logger.warning("get_vector_hits: LLM API unavailable, trying CPU embedding fallback")
        embedding = get_cpu_embedding(q)

    if embedding is None:
        logger.warning("get_vector_hits: CPU embedding also unavailable, semantic rail empty")
        return _dummy_vector_search(q, client), False

    try:
        raw_hits = vector_search(embedding, k=_VECTOR_K, client=client)
    except Exception:
        logger.warning("get_vector_hits: vector_search failed", exc_info=True)
        return _dummy_vector_search(q, client), False

    hits = []
    for h in raw_hits:
        src = h.get("_source", {})
        text = src.get("text", "")
        hits.append({
            "_id":     h.get("_id", ""),
            "score":   round(h.get("_score", 0.0), 3),
            "service": src.get("service_nickname", ""),
            "url":     src.get("url", ""),
            "title":   src.get("title") or src.get("url", ""),
            "snippet": text[:200],
            "context": text[:500],
        })

    return hits, True


def _build_ai_summary(vector_hits, q, llm_session=None, os_client=None, preprocessed_q=None):
    """
    Input:
        vector_hits - list of hit dicts from get_vector_hits
        q           - str, search query
        llm_session - optional requests.Session (injectable for tests)
        os_client   - optional OpenSearch client (injectable for tests)
    Output:
        dict {html, sources} or None if generative model unavailable or no context
    Details:
        Merges vector hits with a BM25 pass over the same query so that
        keyword-relevant chunks (e.g. a "list of X" article whose current entry
        is semantically distant from a generic query) are included alongside the
        nearest-neighbour vector hits. Deduplicates by OpenSearch document ID.
        XSS-safe: LLM output is escaped before being marked safe in the template.
    """
    from flask_app.services.llm import generate_summary
    from flask_app.services.opensearch import bm25_search, get_client
    from markupsafe import escape, Markup

    # Augment vector hits with BM25 hits; use expanded query when available
    # so synonym expansion improves keyword recall for any topic.
    bm25_query = preprocessed_q or q
    try:
        client = os_client or get_client()
        bm25_raw = bm25_search(bm25_query, k=10, client=client)
        bm25_contexts = {}
        for hit in bm25_raw:
            src = hit.get("_source", {})
            bm25_contexts[hit["_id"]] = src.get("text", "")[:500]
    except Exception:
        logger.warning("_build_ai_summary: BM25 augmentation failed", exc_info=True)
        bm25_contexts = {}

    # Merge: BM25 hits first (keyword-precise for factual queries), then vector hits
    # for semantic coverage. Deduplicate by doc ID; cap at 8 total to keep context
    # focused — diluting with 15+ chunks degrades LLM accuracy on factual questions.
    seen_ids = set()
    context_chunks = []
    for doc_id, text in bm25_contexts.items():
        if doc_id not in seen_ids:
            context_chunks.append(text)
            seen_ids.add(doc_id)
    for h in vector_hits:
        hid = h.get("_id", "")
        if hid not in seen_ids:
            context_chunks.append(h["context"])
            seen_ids.add(hid)

    context_chunks = context_chunks[:8]
    if not context_chunks:
        return None

    summary_text = generate_summary(context_chunks, q, session=llm_session)
    if not summary_text:
        return None

    safe_html = Markup(escape(summary_text).replace("\n", Markup("<br>")))
    sources = sorted({h["service"] for h in vector_hits if h.get("service")})
    return {"html": safe_html, "sources": sources}


def semantic_results(q, os_client=None, llm_session=None):
    """
    Input:
        q           - str, the search query
        os_client   - optional OpenSearch client (injectable for tests)
        llm_session - optional requests.Session for LLM API (injectable for tests)
    Output:
        tuple (vector_hits, ai_summary, show_bm25_warning, keyword_chips)
    Details:
        Backward-compatible wrapper used by the JSON /api/search endpoint.
        Calls get_vector_hits, _build_ai_summary, and generate_keywords
        independently so each degrades without blocking the others.
        For the HTMX semantic rail, /api/semantic calls these directly.
    """
    from flask_app.services.llm import generate_keywords

    vector_hits, embedding_up = get_vector_hits(q, os_client=os_client, llm_session=llm_session)
    ai_summary = _build_ai_summary(vector_hits, q, llm_session=llm_session)
    context_for_chips = [h["snippet"] for h in vector_hits[:3]]
    chips = generate_keywords(q, context_for_chips, session=llm_session)

    return vector_hits, ai_summary, not embedding_up, chips


def hybrid_search(query, k=10, client=None, llm_session=None):
    """
    Input:
        query      - str, the search query (should already be preprocessed)
        k          - int, max results to return after fusion (default 10)
        client     - optional OpenSearch client (injectable for tests)
        llm_session - optional requests.Session for LLM API (injectable for tests)
    Output:
        list[dict] — top-k result dicts sorted by descending RRF score, each
        containing _source fields merged with an 'rrf_score' float field.
    Details:
        Runs BM25 and vector search in parallel via ThreadPoolExecutor.
        Applies Reciprocal Rank Fusion (RRF): for each document at rank r
        in list L, its score increases by 1 / (_RRF_K + r). Documents
        appearing in both lists are summed. Returns the top-k by fused score.
        Falls back to BM25-only results when get_embedding() returns None
        (LLM API unavailable) rather than raising.
    """
    from flask_app.services.opensearch import bm25_search, vector_search, get_client as _get_client
    from flask_app.services.llm import get_embedding

    os_client = client or _get_client()

    bm25_hits = []
    vec_hits = []

    def _run_bm25():
        return bm25_search(query, k=k * 2, client=os_client)

    def _run_vector():
        emb = get_embedding(query, session=llm_session)
        if emb is None:
            return None, []
        return emb, vector_search(emb, k=k * 2, client=os_client)

    with ThreadPoolExecutor(max_workers=2) as executor:
        bm25_future = executor.submit(_run_bm25)
        vec_future = executor.submit(_run_vector)

        try:
            bm25_hits = bm25_future.result()
        except Exception:
            logger.warning("BM25 search failed in hybrid_search", exc_info=True)
            bm25_hits = []

        embedding, vec_hits_result = None, []
        try:
            embedding, vec_hits_result = vec_future.result()
        except Exception:
            logger.warning("Vector search failed in hybrid_search", exc_info=True)

        if embedding is not None:
            vec_hits = vec_hits_result

    # RRF fusion
    scores: dict[str, float] = {}
    sources: dict[str, dict] = {}

    for rank, hit in enumerate(bm25_hits):
        doc_id = hit["_id"]
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (_RRF_K + rank)
        sources[doc_id] = hit

    for rank, hit in enumerate(vec_hits):
        doc_id = hit["_id"]
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (_RRF_K + rank)
        if doc_id not in sources:
            sources[doc_id] = hit

    ranked = sorted(scores.items(), key=lambda x: -x[1])
    results = []
    for doc_id, rrf_score in ranked[:k]:
        hit = sources[doc_id]
        merged = dict(hit)
        merged["rrf_score"] = round(rrf_score, 6)
        results.append(merged)
    return results


if __name__ == "__main__":
    pass
