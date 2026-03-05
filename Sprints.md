# SHSE — Sprint Backlog

> Solo dev · 4h/week · 2-week sprints (8h per sprint)
> Comfortable with Python; Flask basics covered. Budget extra time for Elasticsearch mapping and Celery setup — both have configuration-heavy onboarding.

---

## Alpha — Core Loop
*Crawl → Index → Search. Proves the concept. Local auth only, no AI, minimal polish.*

---

### Sprint 1 — Foundation (8h)
*Goal: Repo structure, config, DB, and a running Flask shell*

* [ ] Read Flask app factory pattern and blueprints (~1h familiarization, not a task but budget it)
* [ ] Set up repo structure (Flask app factory pattern, blueprints for `search`, `admin`, `auth`)
* [ ] Define `.env.example` with all service endpoint variables
* [ ] Write `docker-compose.yml` reference stack (all services co-located)
* [ ] Design and write MariaDB schema (`users`, `search_history`, `crawler_targets`, `crawl_jobs`)
* [ ] Write SQLAlchemy models for all tables
* [ ] Implement database migrations (Flask-Migrate / Alembic)
* [ ] Validate connectivity to all external services on Flask startup (ES, MariaDB, Redis, Nutch, Ollama)

---

### Sprint 2 — Authentication (8h)
*Goal: Working login, roles, and first-run setup*

* [ ] Implement local password auth (Flask-Login + bcrypt)
* [ ] Build login / logout / registration views
* [ ] Implement role system (`admin`, `user`) on `users` table
* [ ] Build first-run `/setup` flow to create initial admin account
* [ ] Restrict all `/admin` routes to `admin` role

---

### Sprint 3 — Elasticsearch (8h)
*Goal: Index defined, BM25 search working end-to-end*

* [ ] Spend time with ES docs on index mappings and the Python client before coding (~1h)
* [ ] Confirm Nutch version (1.x vs 2.x) and REST API surface — **blocker for Sprint 5**
* [ ] Define index mapping (`url`, `port`, `text`, `embedding`, `title`, `crawled_at`, `service_nickname`, `content_type`, `vectorized`)
* [ ] Implement index creation on first run
* [ ] Implement document chunking (800 token chunk size)
* [ ] Implement BM25 search query
* [ ] Implement index wipe + rebuild (reindex all)
* [ ] Implement per-target document deletion

---

### Sprint 4 — Search UI (8h)
*Goal: Usable search frontend with history*

* [ ] Build search page (query input, result list with URL / title / snippet)
* [ ] Implement BM25 result rendering
* [ ] Save each query to `search_history` in MariaDB
* [ ] Build search history view for logged-in users
* [ ] Build system health panel (ES, Nutch, Ollama, Redis connectivity)
* [ ] Surface connectivity status in admin UI health panel
* [ ] Add Nginx config with reverse proxy and TLS termination

---

### Sprint 5 — Crawler Config + Nutch Integration (8h)
*Goal: YAML config parsed and Nutch crawl triggerable manually*

* [ ] Define YAML schema for crawler config (`defaults` + `targets`)
* [ ] Implement YAML parser with defaults fallback
* [ ] Validate config on upload (required fields, type checking)
* [ ] Store parsed targets in MariaDB `crawler_targets` table
* [ ] Store raw YAML blob alongside parsed fields
* [ ] Implement `tls_verify` flag per target and globally
* [ ] Implement Nutch job trigger (seed URL generation from target config)
* [ ] Implement Nutch job status polling
* [ ] Implement crawled content retrieval from Nutch output
* [ ] Handle self-signed certs in Nutch (`nutch-site.xml` patch for `tls_verify: false` targets)

---

### Sprint 6 — Celery + Indexing Pipeline (8h)
*Goal: Background crawl-index pipeline working via Celery*

* [ ] Read Celery docs: task definition, delay(), Redis broker config, Beat scheduler (~1h)
* [ ] Set up Celery app with Redis broker
* [ ] Implement `crawl_target(target_id)` task
* [ ] Implement `crawl_all()` task
* [ ] Implement `reindex_target(target_id)` task (delete + recrawl + reindex)
* [ ] Implement `reindex_all()` task (wipe ES + crawl all + index all)
* [ ] Implement `scheduled_crawl()` task
* [ ] Configure Celery Beat with schedules parsed from crawler YAML config
* [ ] Store Celery task IDs in MariaDB `crawl_jobs` table
* [ ] Implement job status polling endpoint for admin UI

> Alpha complete after Sprint 6

---

## MVP — Full Feature Set
*AI summaries, SSO, full admin UI, deferred vectorization, TLS handling. Deployable for others.*

---

### Sprint 7 — Admin UI (8h)
*Goal: Full admin panel wired to Celery tasks and job status*

* [ ] Build crawler target list view
* [ ] Build YAML config upload / inline editor
* [ ] Add per-target action buttons (Crawl, Reindex)
* [ ] Add global action buttons (Crawl All, Reindex All, Vectorize Deferred)
* [ ] Build crawl job status dashboard (live polling via task ID)
* [ ] Disable action buttons with warning when dependent service is unreachable
* [ ] Add warning banner when `tls_verify: false` is active on any target

---

### Sprint 8 — Ollama Integration (8h)
*Goal: Embeddings, AI summaries, and deferred vectorization working*

* [ ] Implement embedding call (chunk → vector via embedding model)
* [ ] Implement vector (cosine similarity) search query in ES
* [ ] Implement graceful degradation — index without embedding if Ollama unreachable
* [ ] Implement `vectorize_pending()` Celery task (batch embed `vectorized=false` docs)
* [ ] Implement generative summary call (RAG context + query → summary)
* [ ] Implement AI summary card above search results
* [ ] Add per-user toggle for AI summaries in settings
* [ ] Expose model selection in admin settings (embedding model + generative model)

---

### Sprint 9 — SSO (8h)
*Goal: OIDC SSO working alongside local auth*

* [ ] Add OIDC SSO support via Authlib (`SSO_ENABLED` config flag)
* [ ] Implement SSO user provisioning on first login
* [ ] Implement role mapping from OIDC claims
* [ ] Allow local auth to remain active alongside SSO (`AUTH_LOCAL_ENABLED` flag)
* [ ] Document OIDC setup for Authentik

> MVP complete after Sprint 9

---

## Production — Hardened & Published
*End-to-end tested, fully documented, ready to share.*

---

### Sprint 10 — Hardening & Docs (8h)
*Goal: Production-ready deployment, documentation complete*

* [ ] Write deployment guide (single VM and multi-VM)
* [ ] Write Nutch setup guide (REST server mode, CA cert mounting)
* [ ] Write Ollama setup guide (model selection, GPU passthrough)
* [ ] Write crawler YAML config reference
* [ ] Document how to point each service at an external host
* [ ] Document CA cert mounting into Nutch JVM trust store
* [ ] Review and clean up all `tls_verify` warning surfaces
* [ ] End-to-end integration test (full crawl → index → search → AI summary flow)
* [ ] Update `README.md` and `TODO.md`

> Production complete after Sprint 10