# Celery Tasks

SHSE uses Celery with a Redis broker to run crawl and vectorization work asynchronously.

---

## Task Signatures

### `celery_worker.tasks.crawl`

| Task | Signature | Description |
|---|---|---|
| `crawl_target` | `crawl_target(target_id)` | Dispatch a single target by DB ID; creates a CrawlJob row |
| `crawl_all` | `crawl_all()` | Fan-out: dispatches `crawl_target.delay()` for every `CrawlerTarget` row |
| `scheduled_crawl` | `scheduled_crawl(nickname)` | Celery Beat entry point; looks up target by nickname and crawls |
| `harvest_oai` | `harvest_oai(target_id)` | Standalone OAI-PMH harvest (delegates to `crawl_target`) |
| `harvest_feeds` | `harvest_feeds(target_id)` | Standalone feed harvest (delegates to `crawl_target`) |
| `push_api_content` | `push_api_content(target_id)` | Standalone api-push harvest (delegates to `crawl_target`) |

### `celery_worker.tasks.index`

| Task | Signature | Description |
|---|---|---|
| `reindex_target` | `reindex_target(target_id)` | Delete OpenSearch docs for target, then re-crawl |
| `reindex_all` | `reindex_all()` | Wipe entire OpenSearch index, then `crawl_all` |

### `celery_worker.tasks.vectorize`

| Task | Signature | Description |
|---|---|---|
| `vectorize_pending` | `vectorize_pending()` | Paginate `vectorized=false` docs; embed via LLM API; update each doc |

---

## Celery Beat Schedule Configuration

Schedules are loaded at Beat startup via the `on_after_finalize` signal in
`celery_worker/app.py`. The `load_beat_schedule()` function queries all
`CrawlerTarget` rows from MariaDB, calls `flask_app.config_parser.to_beat_entry()`
on each, and populates `celery.conf.beat_schedule`. Targets without a `schedule_yaml`
value are skipped. Any DB failure is swallowed so Beat starts cleanly even if MariaDB
is temporarily unreachable.

Each Beat entry maps to `celery_worker.tasks.crawl.crawl_target` with the target's
nickname as the sole positional argument:

```python
celery.conf.beat_schedule = {
    "weekly-myblog": {
        "task": "celery_worker.tasks.crawl.crawl_target",
        "schedule": crontab(hour=2, minute=0, day_of_week=0),
        "args": ["myblog"],
    },
    ...
}
```

The schedule reflects the DB state at worker boot. To apply a new YAML config to
the running Beat scheduler, restart the `celery_beat` container after uploading
the config.

### Beat persistence (redbeat)

Beat uses **celery-redbeat** (`celery-redbeat==2.3.3`) to persist schedule state
in Redis. This means:

- Schedule entries survive `celery_beat` container restarts
- Overdue tasks fire on next startup rather than being skipped
- Schedule state is stored under the `redbeat:` key prefix in Redis

Configuration in `celery_worker/app.py`:
```python
celery.conf.update(
    beat_scheduler="redbeat.RedBeatScheduler",
    redbeat_redis_url=_REDIS_URL,
    redbeat_lock_timeout=60,
)
```

---

## `CrawlJob` Lifecycle

| Status | When set |
|---|---|
| `started` | At the beginning of `crawl_target` / `_crawl_target_impl` |
| `success` | After the harvest function returns without exception |
| `failure` | When any exception is raised during harvesting |

`started_at` is set when the job row is created. `finished_at` is set on both success and failure.

Rows are NOT deleted on completion — they persist for the jobs page in the admin UI.

---

## Retry / Failure Behavior

- No automatic Celery retry is configured. Failed jobs set `CrawlJob.status = "failure"` and
  raise the original exception so Celery records the task as failed.
- Operators can re-dispatch failed targets via the admin UI (triggers a fresh `crawl_target.delay()`).
- `vectorize_pending` silently skips docs where the LLM API returns `None`; they remain
  `vectorized=false` and are picked up by the next `vectorize_pending` run.

---

## Source-type Tags

Each ingest path writes a `source_type` field to OpenSearch:

| Path | `source_type` |
|---|---|
| Nutch crawl (`service`, `network` targets) | `nutch` |
| OAI-PMH harvest | `oai-pmh` |
| Feed harvest (RSS/Atom/ActivityPub) | `rss` |
| API push (custom adapter) | `api-push` |
