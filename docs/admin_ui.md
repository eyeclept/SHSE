# SHSE - Admin UI

All admin routes require the `admin` role, enforced by the `@admin_required`
decorator in `flask_app/routes/admin.py` and by an Nginx `auth_request` at
the proxy layer.

---

## Admin Route Reference

| Method | Path | Endpoint | Description |
|---|---|---|---|
| GET | `/admin/` | `admin.index` | Dashboard - health, stats, recent activity |
| GET | `/admin/_health` | `admin.health_partial` | HTMX poll target - health grid only |
| GET | `/admin/targets` | `admin.targets` | All crawler targets with action buttons |
| POST | `/admin/targets/<id>/crawl` | `admin.crawl_target` | Dispatch crawl task |
| POST | `/admin/targets/<id>/reindex` | `admin.reindex_target` | Dispatch reindex task |
| POST | `/admin/crawl-all` | `admin.crawl_all` | Crawl all targets |
| POST | `/admin/reindex-all` | `admin.reindex_all` | Wipe + rebuild entire index |
| POST | `/admin/vectorize` | `admin.vectorize_pending` | Backfill embeddings |
| GET | `/admin/jobs` | `admin.jobs` | Crawl job list with status filter |
| GET | `/admin/jobs/_table` | `admin.jobs_table` | HTMX poll target - tbody only |
| GET/POST | `/admin/config` | `admin.crawler_config` | YAML editor + file upload |
| POST | `/admin/config/_validate` | `admin.config_validate` | HTMX - live YAML validation |
| GET | `/admin/index` | `admin.index_ops` | Index operations (reindex/vectorize/drop) |
| POST | `/admin/index/reindex_all` | `admin.reindex_all_from_index` | Full reindex |
| POST | `/admin/index/vectorize_all` | `admin.vectorize_all` | Vectorize all pending |
| POST | `/admin/index/drop` | `admin.wipe_index` | Drop + recreate index (requires `confirm_text=DROP`) |

---

## Health Check Endpoints

`_check_services()` in `flask_app/routes/admin.py` probes five services with
a `_PROBE_TIMEOUT = 3` second timeout each. Returns a dict keyed by service
name with `{status, latency_ms, message}`:

| Service | Probe method |
|---|---|
| `opensearch` | `client.cluster.health()` - green/yellow/degraded, red/down |
| `nutch` | `GET http://{NUTCH_HOST}:{NUTCH_PORT}/admin/` |
| `llm_api` | `GET {LLM_API_BASE}/models` |
| `redis` | `redis.Redis.ping()` |
| `mariadb` | `db.session.execute(text("SELECT 1"))` |

The dashboard health grid polls every 5 seconds via HTMX:
```html
<div id="health-grid"
     hx-get="{{ url_for('admin.health_partial') }}"
     hx-trigger="every 5s"
     hx-swap="innerHTML">
```

---

## Job Management

`CrawlJob` rows are written by Celery tasks (not by admin routes). The jobs
page reads the DB and displays status, duration, and target nickname.

The `_jobs_rows.html` tbody polls every 2 seconds via HTMX when active jobs
are present. Polling stops automatically when no running jobs remain (the
front end can implement this with `hx-trigger="every 2s [document.querySelector('.job-running')]"`).

**Status values:** `started` | `success` | `failure`

---

## YAML Config Upload

`POST /admin/config` accepts either:
- `yaml=<text>` - textarea content
- `upload=<file>` - multipart file upload

The route calls `parse_config(yaml_str)` then `persist_targets(yaml_str, parsed, db.session)`.
A full replace is performed: all existing `CrawlerTarget` rows are deleted and replaced.
`CrawlJob` rows with a reference to deleted targets have their `target_id` set to NULL
(history preserved, reference nulled).

Live YAML validation is available at `POST /admin/config/_validate` - returns the
`_yaml_validation.html` fragment via HTMX with a 600ms debounce.

---

## Index Operations

Destructive operations on the `/admin/index` page require confirmation:

- **Reindex all** - dispatches `reindex_all.delay()`; no confirmation required
- **Vectorize all** - dispatches `vectorize_pending.delay()`; no confirmation required
- **Drop + recreate** - requires form field `confirm_text == "DROP"` to prevent
  accidental wipe; calls `wipe_index()` then `create_index()`
