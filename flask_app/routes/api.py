"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    JSON search API blueprint. Exposes OpenSearch results as structured JSON
    so clients other than the browser (CLI, scripts, integrations) can query
    the index without parsing HTML.
"""
# Imports
import math

from flask import Blueprint, jsonify, request
from flask_app.services.opensearch import get_client

# Globals
api_bp = Blueprint("api", __name__, url_prefix="/api")

_INDEX_NAME = "shse_pages"
_PAGE_SIZE = 10


# Functions
@api_bp.route("/search")
def search():
    """
    Input: q (query string), page (1-indexed, default 1), tab (default 'all')
    Output: JSON object with results, total, timing, and source facets
    Details:
        Runs a BM25 match query against the shse_pages index with highlighting.
        Returns 200 with an empty results list when q is blank.
        Returns 200 with an empty results list when OpenSearch is unreachable.

    Response shape:
        {
          "q":          str,
          "tab":        str,
          "page":       int,
          "page_count": int,
          "total":      int,
          "took_ms":    int,
          "results": [
            {
              "id":           str,
              "title":        str,
              "url":          str,
              "service":      str,
              "port":         int,
              "crawled_at":   str,
              "content_type": str,
              "snippet":      str,
              "vectorized":   bool
            }
          ],
          "sources": [{"name": str, "n": int}]
        }
    """
    q = request.args.get("q", "").strip()
    tab = request.args.get("tab", "all")
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    result_rows = []
    total = 0
    took_ms = 0
    sources = []
    page_count = 1

    if q:
        try:
            client = get_client()
            body = {
                "from": (page - 1) * _PAGE_SIZE,
                "size": _PAGE_SIZE,
                "query": {"match": {"text": {"query": q, "fuzziness": "AUTO"}}},
                "highlight": {
                    "fields": {"text": {}},
                    "pre_tags": [""],
                    "post_tags": [""],
                    "number_of_fragments": 2,
                    "fragment_size": 200,
                },
                "aggs": {
                    "by_service": {"terms": {"field": "service_nickname", "size": 20}},
                },
            }
            resp = client.search(index=_INDEX_NAME, body=body)
            took_ms = resp.get("took", 0)
            total = resp["hits"]["total"]["value"]
            page_count = max(1, math.ceil(total / _PAGE_SIZE))

            for h in resp["hits"]["hits"]:
                src = h.get("_source", {})
                hl = h.get("highlight", {})
                snippet = " … ".join(hl.get("text", [src.get("text", "")[:300]]))
                result_rows.append({
                    "id": h["_id"],
                    "title": src.get("title") or src.get("url", ""),
                    "url": src.get("url", ""),
                    "service": src.get("service_nickname", ""),
                    "port": src.get("port", 80),
                    "crawled_at": (src.get("crawled_at") or "")[:19],
                    "content_type": src.get("content_type", ""),
                    "snippet": snippet,
                    "vectorized": bool(src.get("vectorized", False)),
                })

            buckets = resp.get("aggregations", {}).get("by_service", {}).get("buckets", [])
            sources = [{"name": b["key"], "n": b["doc_count"]} for b in buckets]

        except Exception:
            pass

    return jsonify({
        "q": q,
        "tab": tab,
        "page": page,
        "page_count": page_count,
        "total": total,
        "took_ms": took_ms,
        "results": result_rows,
        "sources": sources,
    })


@api_bp.route("/stats")
def stats():
    """
    Input: None
    Output: JSON object with document count, service count, and last crawl time
    Details:
        Returns zeros when OpenSearch is unreachable.
    """
    try:
        client = get_client()
        count = client.count(index=_INDEX_NAME).get("count", 0)
        agg = client.search(index=_INDEX_NAME, body={
            "size": 0,
            "aggs": {"svc": {"cardinality": {"field": "service_nickname"}}},
        })
        svc_count = agg["aggregations"]["svc"]["value"]
        last = client.search(index=_INDEX_NAME, body={
            "size": 1, "sort": [{"crawled_at": "desc"}], "_source": ["crawled_at"],
        })
        hits = last["hits"]["hits"]
        last_crawl = hits[0]["_source"].get("crawled_at", "")[:19] if hits else None
        return jsonify({"docs": count, "services": svc_count, "last_crawl": last_crawl})
    except Exception:
        return jsonify({"docs": 0, "services": 0, "last_crawl": None})


if __name__ == "__main__":
    pass
