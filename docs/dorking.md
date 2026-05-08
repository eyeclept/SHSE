# Google Dorking — Advanced Search Operators

SHSE supports Google-style search operators so power users can write precise queries. Operators are parsed transparently: queries with no operators fall back to the standard BM25 multi-match search.

---

## Supported Operators

| Operator | Example | Effect |
|---|---|---|
| `site:` | `site:kiwix human` | Filter to docs whose URL contains `kiwix` |
| `intitle:` | `intitle:anatomy` | Match only in the `title` field |
| `inurl:` | `inurl:/A/` | Filter to docs whose URL path contains `/A/` |
| `filetype:` | `filetype:html` | Filter by `content_type` field |
| `"phrase"` | `"human anatomy"` | Exact phrase match anywhere in the document |
| `-term` | `human -animal` | Exclude docs containing `animal` |

---

## Query Syntax Examples

```
# All pages from the Kiwix service about the human body
site:kiwix human body

# Only pages whose title contains "cell"
intitle:cell biology

# Pages under the /A/ path
inurl:/A/ encyclopedia

# HTML pages only
filetype:html tutorial

# Exact phrase match
"mitochondria is the powerhouse"

# Exclude a term
python -snake

# Combine multiple operators
site:kiwix intitle:biology "cell division" -virus filetype:html
```

---

## How Operators Map to OpenSearch DSL

Internally, `bm25_body_with_dorks()` in `flask_app/services/search.py` translates the parsed query into an OpenSearch `bool` query:

| Operator | DSL clause type | Target field |
|---|---|---|
| `site:value` | `filter` → `wildcard` | `url` |
| `inurl:value` | `filter` → `wildcard` | `url` |
| `intitle:value` | `filter` → `match` | `title` |
| `filetype:value` | `filter` → `term` | `content_type` |
| `"phrase"` | `must` → `match_phrase` | `text` |
| `-term` | `must_not` → `multi_match` | `title`, `text` |
| plain terms | `must` → `multi_match` | `title^2`, `text` |

Plain terms use `fuzziness: AUTO` and `prefix_length: 1` for typo tolerance, identical to the standard search.

---

## Known Limitations

- **Operator values cannot contain spaces.** `site:my site.com` will treat `site.com` as a separate plain term. Use `site:my.site.com` instead.
- **`site:` and `inurl:` use wildcard matching** on the stored URL string. Performance degrades for very short values (e.g. `site:a`) that match nearly every document.
- **`filetype:` matches the exact `content_type` field value.** Common values are `text/html`, `application/pdf`. The operator strips the full MIME string, so `filetype:html` matches `text/html`.
- **Multiple instances of the same operator** — only the last occurrence is used (e.g. `site:kiwix site:openzim` uses `openzim`).
- **No nested grouping** — operators like `(a OR b)` are not supported.
