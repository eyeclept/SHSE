# SHSE — User and Operator Guide

This guide covers day-to-day use of SHSE: first-run setup, adding services to crawl, running and monitoring crawl jobs, searching, and managing the index.

---

## First Run

### 1. Start the stack

```bash
docker compose up -d
bash init.sh          # confirm all services healthy
```

### 2. Create the admin account

Navigate to `http://localhost:8888/setup` in your browser. This page only appears when no admin account exists. Enter a username and password; you will be redirected to the login page.

### 3. Create the OpenSearch index

```bash
python cli.py create-index
```

This is a no-op if the index already exists, so it is safe to run at any time.

### 4. Verify Nutch is running

The Nutch REST server starts automatically when the container starts (configured in `docker-compose.yml`). Confirm it is healthy:

```bash
curl http://localhost:8081/admin/
```

If it returns JSON, the server is up. The admin health grid at `/admin/` also shows Nutch status.

---

## Adding Services to Crawl

### Write a YAML config

Create a file (e.g. `my-config.yaml`) following the format in [docs/config.md](config.md):

```yaml
defaults:
  service: http
  port: 80
  tls_verify: true
  crawl_depth: 2              # BFS hops from seed URL; 0 = seed page only
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
    route: /                  # seed URL path

  - type: service
    nickname: gitea
    url: git.homelab.lan
    port: 3000
    crawl_depth: 1            # override: shallower crawl for Gitea

  - type: network
    network: 192.168.1.0/24
    schedule:
      frequency: monthly
      day: 1
      time: "03:00"
      timezone: UTC
```

Every target inherits from `defaults`. Override any field at the target level.

**`crawl_depth`** controls how many link-hops the BFS crawler follows from the seed URL:
- `0` — index the seed page only
- `1` — seed page + all pages directly linked from it
- `2` (default) — two hops; reaches most single-level site structures
- Higher values follow more links but take proportionally longer

Set `crawl_depth` in YAML or edit it per-target in Admin → Targets.

### Upload the config

```bash
python cli.py upload-config my-config.yaml
```

Or paste it into the admin UI at `/admin/config`.

Uploading a new config **replaces all existing targets**. Previous crawl job history is preserved (target references become null).

### Verify the targets

```bash
python cli.py list-targets
```

Output:
```
id    nickname                  type        url / network                     schedule
------------------------------------------------------------------------------------------
   1  homelab-docs              service     docs.homelab.lan                  weekly
   2  gitea                     service     git.homelab.lan                   weekly
   3  (null)                    network     192.168.1.0/24                    monthly
```

---

## Crawling

### Trigger a crawl immediately

```bash
# Single target
python cli.py crawl homelab-docs

# All targets
python cli.py crawl-all
```

Both commands dispatch Celery tasks and return immediately, printing the task ID:
```
dispatched crawl for 'homelab-docs' (target 1)
task id: 3f2a1b9c-...
```

The crawl runs in the background. Monitor progress with `python cli.py jobs`.

### Scheduled crawls

Schedules defined in the YAML config are loaded automatically when the Celery Beat service starts. To apply a new schedule after uploading a config:

```bash
docker compose restart celery_beat
```

### Monitor jobs

```bash
python cli.py jobs
python cli.py jobs --limit 5    # show only the 5 most recent
```

Output:
```
id      nickname                  status      started              task_id
------------------------------------------------------------------------------------------
     4  homelab-docs              success     2026-04-25 10:15:00  3f2a1b9c-...
     3  gitea                     failure     2026-04-25 09:00:00  a1b2c3d4-...
     2  192.168.1.0/24            success     2026-04-24 03:00:00  e5f6a7b8-...
```

`success` means the crawl pipeline completed without error. `failure` means an exception was raised — check the Celery worker logs for details:

```bash
docker compose logs celery_worker --tail=50
```

---

## Searching

### Browser

Navigate to `http://localhost:8888`. Type a query and press Enter or click the search button.

### CLI

```bash
python cli.py search "nginx reverse proxy"
python cli.py search "homelab" --page 2
```

Output:
```
3 results for "nginx reverse proxy"  (8ms)  page 1/1

  [1] Nginx — Homelab Docs
      service: homelab-docs
      http://docs.homelab.lan/nginx
      Nginx is a web server that can also be used as a reverse proxy …
      and load balancer. This guide covers the basic configuration …

  [2] ...
```

### API

```bash
curl "http://localhost:8888/api/search?q=nginx"
curl "http://localhost:8888/api/search?q=nginx&page=2"
curl "http://localhost:8888/api/stats"
```

---

## Index Management

### Check index stats

```bash
python cli.py stats
```

```
documents : 14,021
services  : 6
last crawl: 2026-04-25T10:15:00
```

### Reindex a single target

Deletes all OpenSearch documents for that target and re-crawls from scratch. Use when content has changed significantly.

```bash
python cli.py reindex homelab-docs
```

### Reindex everything

Wipes the entire index and re-crawls all targets. **This destroys all indexed content** and takes as long as all crawls combined.

```bash
python cli.py reindex-all --yes
```

### Backfill embeddings (AI summaries)

If the LLM API was unavailable during indexing, documents are stored without vectors (`vectorized=false`). Backfill them once the API is reachable:

```bash
python cli.py vectorize
```

This can also be run after switching embedding models to update all vectors.

---

## Self-Signed Certificates

If a service uses a self-signed TLS certificate, set `tls_verify: false` in the target config:

```yaml
targets:
  - type: service
    nickname: internal-app
    url: app.homelab.lan
    port: 443
    service: https
    tls_verify: false
```

This disables certificate verification only for that target. Nutch will still crawl the site; it just will not verify the certificate chain.

> The recommended long-term fix is to add your homelab root CA to the Nutch container's JVM trust store so `tls_verify: true` can remain set globally.

---

## User Management

### Register a user

Visit `/register` in the browser, or ask the admin to create an account.

All self-registered accounts receive the `user` role. Admins are created only via `/setup` (first run) or by manually updating the `role` column in the database.

### SSO

If `SSO_ENABLED=true`, users can log in via the OIDC provider at `/sso/login`. Role assignment is automatic: members of the `SSO_ADMIN_GROUP` group (default: `admin`) receive the admin role on every login.

### Theme

Toggle between light and dark mode using the user menu (hamburger icon, top-right corner of every page).

---

## AI Summaries and Semantic Search

When `LLM_API_BASE` is configured, the search results page shows a right-rail panel that loads asynchronously after the main BM25 results:

1. **Suggested keywords** — Short phrases extracted from semantic results to help refine your query. Appear as grey chips at the top of the rail.
2. **AI summary** — A 2–4 sentence RAG answer synthesised from the top vector matches. Collapsible, with source citations.
3. **Semantic matches** — The top-k vector hits with relevance scores, independent from the BM25 result set.

The entire rail loads via a single HTMX request to `/api/semantic?q=...`. BM25 results are never blocked by it. If the LLM API is unreachable the rail loads silently with no content.

Toggle the AI summary per-user at `/settings` → AI summary switch.

To check LLM API connectivity, visit `/admin/` and look at the health grid.

### Automatic vectorization

After every successful crawl, a `vectorize` job is automatically dispatched to backfill any documents that were indexed without embeddings (e.g. if the LLM API was down during the crawl). The job appears in Admin → Jobs with kind `vectorize`. To trigger it manually:

```bash
python cli.py vectorize
```

### Models

| Env var | Purpose | Default |
|---|---|---|
| `LLM_EMBED_MODEL` | Embedding model | `nomic-embed-text` |
| `LLM_GEN_MODEL` | Summary / keyword model | `llama3` |

---

## Admin Dashboard

The admin dashboard at `/admin/` shows live service health (polls every 5 seconds):

| Indicator | Source |
|---|---|
| OpenSearch | `cluster.health()` — green/yellow/red |
| Nutch | `GET /admin/` on the Nutch REST server |
| LLM API | `GET {LLM_API_BASE}/models` |
| Redis | `PING` |
| MariaDB | `SELECT 1` |

If the Nutch or OpenSearch indicators show **Down**, crawl and reindex buttons on the
Targets page will be disabled in the UI.

---

## Kiwix Test Server (dev/test only)

A Kiwix server with a 100-article Wikipedia ZIM is included for end-to-end testing. It is not started during normal stack boot.

```bash
# Start
docker compose --profile test up kiwix -d

# Add as a crawl target.
# Inside Docker, container-to-container port is 8080 (not the host-mapped 8082).
# Route to the ZIM content root so articles are one hop from the seed.
# crawl_depth: 1 is enough — the index page links to all 97 articles directly.
cat > /tmp/kiwix-target.yaml << 'EOF'
defaults: {}
targets:
  - type: service
    nickname: kiwix-wikipedia
    url: kiwix
    port: 8080
    route: /content/wikipedia_en_100_nopic_2026-04/
    service: http
    tls_verify: false
    crawl_depth: 1
EOF
python cli.py upload-config /tmp/kiwix-target.yaml

# Crawl it
python cli.py crawl kiwix-wikipedia

# Search for something
python cli.py search "animal"

# Stop when done
docker compose --profile test down kiwix
```

---

## Troubleshooting

### A crawl fails immediately

1. Check the Celery worker logs: `docker compose logs celery_worker --tail=100`
2. Confirm the Nutch REST server is running: `curl http://localhost:8081/admin/`
3. Confirm the target URL is reachable from within the Docker network: `docker exec flask curl -s http://<target-url>`

### Search returns no results

1. Run `python cli.py stats` — if `documents: 0`, the index is empty. Run a crawl first.
2. Confirm the OpenSearch index exists: `python cli.py create-index`
3. Check that at least one crawl job completed with `success` status: `python cli.py jobs`

### AI summaries not showing

1. Check `LLM_API_BASE` is set correctly in `.env`.
2. Test the endpoint directly: `curl ${LLM_API_BASE}/models`
3. If the API was down during crawling, run `python cli.py vectorize` to backfill embeddings.

### Scheduled crawls not running

1. Confirm `celery_beat` is running: `docker compose ps celery_beat`
2. Restart Beat after uploading a new config: `docker compose restart celery_beat`
3. Check Beat logs: `docker compose logs celery_beat --tail=50` — look for lines like `beat: Starting...` followed by the schedule entries.
