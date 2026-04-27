# SHSE - Usage Guide

Day-to-day reference for searching, managing crawl targets, monitoring jobs, and using the admin tools.

---

## Searching

### Basic search

Type a query in the search box and press Enter. Results appear immediately from BM25 full-text search. If a local LLM API is configured, the right rail loads asynchronously with semantic results and an AI summary.

### Typo tolerance

Queries are automatically fuzzy-matched. `"anmal"` will find documents containing `"animal"`.

### Right rail

| Section | Status | What it shows |
|---|---|---|
| **Suggested keywords** | Working | Short phrases from semantic result titles to help refine your query |
| **AI summary** | Not yet implemented | Planned for a future release (Epic 18) |
| **Semantic matches** | Working | Top-k vector search hits with relevance scores |

The entire rail is optional and loads asynchronously. BM25 results are never blocked by it.

### Search history

Every query you run while logged in is saved to your history. View it at `/history`. Filter by keyword or clear all entries from the same page.

---

## Admin: Crawl Targets

### Add a target

Go to **Admin → Targets** and fill in the form. Required fields depend on the target type:

| Type | Required fields |
|---|---|
| `service` | Nickname, URL, Port |
| `network` | Network CIDR |
| `oai-pmh` | Nickname, URL, Endpoint |
| `feed` | Nickname, URL, Feed path |
| `api-push` | Nickname, URL, Adapter |

**Crawl depth** (service and network targets): controls how many link-hops the BFS crawler follows from the seed URL.
- `0` - seed page only
- `1` - seed + all pages directly linked from it
- `2` (default) - two hops
- Set lower for large sites to avoid crawling too broadly.

**TLS verify**: uncheck for services with self-signed certificates.

### Upload via YAML

Upload a complete target config at **Admin → Config**. Uploading replaces all existing targets. Previous job history is preserved (target references become null).

```yaml
defaults:
  service: http
  tls_verify: true
  crawl_depth: 2
  schedule:
    frequency: weekly
    day: sunday
    time: "02:00"
    timezone: UTC

targets:
  - type: service
    nickname: homelab-docs
    url: docs.homelab.lan
    port: 80

  - type: service
    nickname: gitea
    url: git.homelab.lan
    port: 3000
    crawl_depth: 1
```

### Edit or delete a target

Click **Edit** next to any target in the targets list. Click **Delete** to remove it; associated jobs are preserved with a null target reference.

---

## Admin: Crawling

### Trigger a crawl

- **From the UI**: Admin → Targets → **Crawl** button next to a target
- **From the CLI**: `python cli.py crawl <nickname>` or `python cli.py crawl-all`

Crawl jobs are dispatched to the Celery worker and run in the background. After a successful crawl, a vectorize job is automatically dispatched if the LLM API is configured.

### Scheduled crawls

Schedules are loaded from the YAML config and stored in Redis via redbeat. They survive container restarts without losing the next run time. To apply a new schedule after uploading a config:

```bash
docker compose restart celery_beat
```

---

## Admin: Jobs

**Admin → Jobs** shows all crawl and vectorize jobs with live HTMX polling (updates every 2 seconds).

| Column | Meaning |
|---|---|
| Job | Kind (crawl / vectorize) and status badge |
| Target | Crawler target nickname, or `-` for vectorize jobs |
| Progress | Bar for running jobs; `-` when finished |
| Started | UTC timestamp |
| Took | Wall-clock duration |

Click **Logs** on a failed job to see the error message and Celery traceback.

Filter by status using the chips at the top of the page (All / Queued / Running / Done / Failed).

---

## Admin: Index Operations

**Admin → Index** shows the current index health and provides bulk operations:

| Operation | Effect |
|---|---|
| **Vectorize all** | Backfill embeddings for all `vectorized=false` documents |
| **Reindex all** | Wipe the index and re-crawl all targets from scratch |
| **Drop + recreate** | Destroy all indexed content and rebuild the empty index |

Reindex and drop require confirmation. Drop requires typing `DROP` to proceed.

---

## Admin: System Health

The dashboard at **Admin /** polls live status every 5 seconds:

| Service | Probe |
|---|---|
| OpenSearch | `cluster.health()` - green/yellow/red |
| Nutch | `GET /admin/` on the Nutch REST server |
| LLM API | `GET {LLM_API_BASE}/models` |
| Redis | `PING` |
| MariaDB | `SELECT 1` |
| Celery | broadcast ping to workers |

Crawl and reindex buttons are disabled automatically when OpenSearch or Nutch shows Down.

---

## CLI Reference

```bash
# Search
python cli.py search "query"
python cli.py search "query" --page 2

# Index stats
python cli.py stats

# Targets
python cli.py list-targets
python cli.py upload-config config.yaml

# Crawling
python cli.py crawl <nickname>
python cli.py crawl-all
python cli.py reindex <nickname>
python cli.py reindex-all --yes

# Index management
python cli.py create-index
python cli.py vectorize
python cli.py wipe-index --yes

# Jobs
python cli.py jobs
python cli.py jobs --limit 20
```

---

## Settings

Users can configure personal preferences at **/settings**:

| Setting | Effect |
|---|---|
| Theme | Light or dark mode (also available from the hamburger menu on every page) |
| Change password | Update local account password (requires current password; 8 character minimum) |
| Clear search history | Permanently deletes all saved searches for your account |

---

## Troubleshooting

### Search returns no results

1. `python cli.py stats` - if `documents: 0`, the index is empty. Trigger a crawl.
2. Confirm the crawl completed: `python cli.py jobs` - look for `success` status.
3. If the crawl succeeded but docs are 0, check the target's URL and `crawl_depth` setting. A `crawl_depth: 0` indexes only the seed page.

### Crawl shows success but wrong content

- Check the `route` field. It should point to the content root, not a redirect-only landing page.
- For sites with JS-rendered navigation (single-page apps), set `route` to a static page that lists links directly in its HTML.

### AI summaries not appearing

1. Confirm `LLM_API_BASE` is set in `.env` and the endpoint is reachable.
2. Test: `curl ${LLM_API_BASE}/models` - should return a JSON list of models.
3. Check Admin → health grid for the LLM API indicator.
4. If the API was down during the crawl, run `python cli.py vectorize` to backfill embeddings.

### Vectorize job fails

Check the job logs in Admin → Jobs. Common causes:
- LLM API endpoint returned a non-200 response
- Embedding model name in `LLM_EMBED_MODEL` does not match a loaded model

### Scheduled crawls not running

1. Confirm `celery_beat` is running: `docker compose ps celery_beat`
2. Restart Beat after uploading a new config: `docker compose restart celery_beat`
3. Check Beat logs: `docker compose logs celery_beat --tail=50`

### A service shows "Down" in the health grid

| Service | Likely cause | Fix |
|---|---|---|
| Nutch | REST server not started | Check Nutch container logs; the server auto-starts via the container command |
| LLM API | Wrong `LLM_API_BASE` URL | Confirm the URL from the host machine; use `host.docker.internal` if the API runs on the host |
| OpenSearch | Container still starting | Wait 30–60 seconds after `docker compose up` |
