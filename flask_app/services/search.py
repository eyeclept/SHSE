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
import math

# Globals
_INDEX_NAME = "shse_pages"
_PAGE_SIZE = 10
_VECTOR_K = 5


# Functions
def bm25_body(q, page=1, page_size=_PAGE_SIZE, highlight_tags=None):
    """
    Input:
        q           - str, search query
        page        - int, 1-indexed page number
        page_size   - int, results per page
        highlight_tags - tuple (pre, post) for highlight tags; defaults to plain text
    Output:
        dict — OpenSearch request body for a multi_match BM25 query
    Details:
        Uses multi_match best_fields across `text` and `title` (title boosted 2x).
        fuzziness=AUTO provides 1–2 edit distance tolerance for typos.
        prefix_length=1 prevents fuzzing the first character of each term so
        very short queries don't match everything.
    """
    pre_tag, post_tag = highlight_tags or ("", "")
    return {
        "from": (page - 1) * page_size,
        "size": page_size,
        "query": {
            "multi_match": {
                "query": q,
                "fields": ["title^2", "text"],
                "type": "best_fields",
                "fuzziness": "AUTO",
                "prefix_length": 1,
            }
        },
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


def semantic_results(q, os_client=None, llm_session=None):
    """
    Input:
        q           - str, the search query
        os_client   - optional OpenSearch client (injectable for tests)
        llm_session - optional requests.Session for LLM API (injectable for tests)
    Output:
        tuple (vector_hits, ai_summary, show_bm25_warning, keyword_chips) where:
            vector_hits      - list[dict] for the right-rail semantic results
            ai_summary       - dict {html, sources} or None
            show_bm25_warning - bool, True when LLM API is unreachable
            keyword_chips    - list[str] of suggested related search terms
    Details:
        Embeds the query, runs k-NN vector search, and generates a RAG summary.
        Returns empty results and show_bm25_warning=True when the LLM API is down.
        All errors are swallowed — callers always get a valid (possibly empty) result.
    """
    from flask_app.services.llm import get_embedding, generate_summary
    from flask_app.services.opensearch import vector_search, get_client

    client = os_client or get_client()

    try:
        embedding = get_embedding(q, session=llm_session)
    except Exception:
        embedding = None

    if embedding is None:
        return [], None, True, []

    try:
        hits = vector_search(embedding, k=_VECTOR_K, client=client)
    except Exception:
        return [], None, True, []

    vector_hits = []
    context_chunks = []
    sources = set()

    for h in hits:
        src = h.get("_source", {})
        text = src.get("text", "")
        title = src.get("title") or src.get("url", "")
        context_chunks.append(text[:500])
        sources.add(src.get("service_nickname", ""))
        vector_hits.append({
            "score": round(h.get("_score", 0.0), 3),
            "service": src.get("service_nickname", ""),
            "url": src.get("url", ""),
            "title": title,
            "snippet": text[:200],
        })

    ai_summary = None
    if context_chunks:
        try:
            summary_text = generate_summary(context_chunks, q, session=llm_session)
            if summary_text:
                # Escape the raw LLM output before marking it safe for the
                # template. This prevents XSS even if the model produces
                # HTML-like content. Newlines are preserved as <br>.
                from markupsafe import escape, Markup
                safe_html = Markup(escape(summary_text).replace("\n", Markup("<br>")))
                ai_summary = {
                    "html": safe_html,
                    "sources": sorted(sources),
                }
        except Exception:
            pass

    chips = _keyword_chips(vector_hits, q)
    return vector_hits, ai_summary, False, chips


if __name__ == "__main__":
    pass
