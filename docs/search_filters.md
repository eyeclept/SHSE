# Search Filters and Sort Order

## Supported filter parameters

| Parameter | Values | Repeatable | OpenSearch clause |
|---|---|---|---|
| `filter_service` | Any `service_nickname` string (e.g. `kiwix`, `gitea`) | Yes | `terms` filter on `service_nickname` |

Filters are applied as OpenSearch `filter` clauses (inside a `bool` query), so they do not affect relevance scoring — only which documents are returned.

### URL format

Repeat `filter_service` for multiple values:

```
/search?q=nginx&filter_service=kiwix&filter_service=gitea
```

The filter panel on the results page generates this URL automatically when you tick service checkboxes and click **Apply**.

To clear all filters, click **Clear** in the filter panel or remove the `filter_service` params from the URL.

## Sort options

| `sort` value | Label | Behaviour |
|---|---|---|
| `relevance` (default) | Relevance | OpenSearch `_score` ordering (BM25 relevance) |
| `date_desc` | Newest first | `crawled_at` descending, then `_score` as tiebreaker |
| `date_asc` | Oldest first | `crawled_at` ascending, then `_score` as tiebreaker |

Any unrecognised `sort` value is silently coerced to `relevance`.

### URL format

```
/search?q=nginx&sort=date_desc
/search?q=nginx&sort=date_asc
```

Sort and filters can be combined freely:

```
/search?q=nginx&filter_service=kiwix&sort=date_desc
```

## Interaction with dork operators (Epic 16)

Filter params and dork operators are combined additively. When dork operators are present, filters are appended to the `bool.filter` array alongside dork-generated clauses. For example:

```
/search?q=site:kiwix+nginx&filter_service=kiwix&sort=date_desc
```

This produces a bool query whose `filter` array contains both a `wildcard` on `url` (from `site:`) and a `terms` on `service_nickname` (from `filter_service`).

## Known limitations

- Only `filter_service` is implemented. `filter_type` (html/pdf/other) is planned but not yet wired (see TODO item 27, step 1 spec).
- Sort applies to the BM25/dork result set only. The semantic rail (HTMX-loaded vector matches and AI summary) is not affected by sort order.
- The filter panel shows only services that have hits for the current query (`by_service` aggregation). Services with zero hits for the query are not shown as filter options.
- Pagination preserves active filters and sort: each page link includes `filter_service` and `sort` params.
