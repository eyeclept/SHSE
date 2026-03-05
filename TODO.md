# SHSE — Backlog

## Infrastructure & Configuration
* [ ] Define `.env.example` with all service endpoint variables
* [ ] Write `docker-compose.yml` reference stack (all services co-located)
* [ ] Document how to point each service at an external host
* [ ] Add Nginx config with reverse proxy and TLS termination
* [ ] Validate connectivity to all external services on Flask startup (ES, MariaDB, Redis, Nutch, Ollama)
* [ ] Surface connectivity status in admin UI health panel

---

## Database
* [ ] Design and write MariaDB schema (`users`, `search_history`, `crawler_targets`, `crawl_jobs`)
* [ ] Write SQLAlchemy models for all tables
* [ ] Implement database migrations (Flask-Migrate / Alembic)

---

## Authentication
* [ ] Implement local password auth (Flask-Login + bcrypt)
* [ ] Build login / logout / registration views
* [ ] Implement role system (`admin`, `user`) on `users` table
* [ ] Build first-run `/setup` flow to create initial admin account
* [ ] Add OIDC SSO support via Authlib (`SSO_ENABLED` config flag)
* [ ] Implement SSO user provisioning on first login
* [ ] Implement role mapping from OIDC claims
* [ ] Allow local auth to remain active alongside SSO (`AUTH_LOCAL_ENABLED` flag)

---

## Elasticsearch
* [ ] Define index mapping (`url`, `port`, `text`, `embedding`, `title`, `crawled_at`, `service_nickname`, `content_type`, `vectorized`)
* [ ] Implement index creation on first run
* [ ] Implement BM25 search query
* [ ] Implement vector (cosine similarity) search query
* [ ] Implement document chunking (800 token chunk size)
* [ ] Implement index wipe + rebuild (reindex all)
* [ ] Implement per-target document deletion

---

## Crawler Configuration
* [ ] Define YAML schema for crawler config (`defaults` + `targets`)
* [ ] Implement YAML parser with defaults fallback
* [ ] Validate config on upload (required fields, type checking)
* [ ] Store parsed targets in MariaDB `crawler_targets` table
* [ ] Store raw YAML blob alongside parsed fields
* [ ] Implement `tls_verify` flag per target and globally

---

## Apache Nutch Integration
* [ ] Confirm Nutch version (1.x vs 2.x) and REST API surface
* [ ] Implement Nutch job trigger from Celery (seed URL generation from target config)
* [ ] Implement Nutch job status polling
* [ ] Implement crawled content retrieval from Nutch output
* [ ] Handle self-signed certs in Nutch (`nutch-site.xml` patch for `tls_verify: false` targets)
* [ ] Document CA cert mounting into Nutch JVM trust store

---

## Celery + Redis
* [ ] Set up Celery app with Redis broker
* [ ] Implement `crawl_target(target_id)` task
* [ ] Implement `crawl_all()` task
* [ ] Implement `reindex_target(target_id)` task (delete + recrawl + reindex)
* [ ] Implement `reindex_all()` task (wipe ES + crawl all + index all)
* [ ] Implement `vectorize_pending()` task (batch embed `vectorized=false` docs)
* [ ] Implement `scheduled_crawl()` task
* [ ] Configure Celery Beat with schedules parsed from crawler YAML config
* [ ] Store Celery task IDs in MariaDB `crawl_jobs` table
* [ ] Implement job status polling endpoint for admin UI

---

## Ollama Integration
* [ ] Implement embedding call (chunk → vector via embedding model)
* [ ] Implement generative summary call (RAG context + query → summary)
* [ ] Implement graceful degradation — index without embedding if Ollama unreachable
* [ ] Expose model selection in admin settings (embedding model + generative model)
* [ ] Implement deferred vectorization backfill in `vectorize_pending()` task

---

## Flask — Search UI
* [ ] Build search page (query input, result list with URL / title / snippet)
* [ ] Implement BM25 result rendering
* [ ] Implement AI summary card above results (shown when Ollama available + enabled)
* [ ] Add per-user toggle for AI summaries in settings
* [ ] Save each query to `search_history` in MariaDB
* [ ] Build search history view for logged-in users

---

## Flask — Admin UI (`/admin`)
* [ ] Restrict all `/admin` routes to `admin` role
* [ ] Build crawler target list view
* [ ] Build YAML config upload / inline editor
* [ ] Add per-target action buttons (Crawl, Reindex)
* [ ] Add global action buttons (Crawl All, Reindex All, Vectorize Deferred)
* [ ] Build crawl job status dashboard (live polling via task ID)
* [ ] Build system health panel (ES, Nutch, Ollama, Redis connectivity)
* [ ] Disable action buttons with warning when dependent service is unreachable
* [ ] Add warning banner when `tls_verify: false` is active on any target

---

## Documentation
* [ ] Write `README.md`
* [ ] Write `TODO.md`
* [ ] Write deployment guide (single VM and multi-VM)
* [ ] Write Nutch setup guide (REST server mode, CA cert mounting)
* [ ] Write Ollama setup guide (model selection, GPU passthrough)
* [ ] Document OIDC setup for Authentik
* [ ] Write crawler YAML config reference

---

## Moonshot (Future / Out of Scope v1)
* [ ] Expand AI window / chat mode (separate project)
* [ ] Network diagram software config import
* [ ] Per-user crawler config isolation
* [ ] Celery Beat DB backend for schedule persistence across restarts