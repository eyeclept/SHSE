---
session: 2026-03-24T00:00
status: complete
---
## Done
- Replaced all Elasticsearch references with OpenSearch in `DesignDoc.md` (ES abbreviations, pipeline descriptions, admin UI table, MCP section)
- Replaced all Elasticsearch references with OpenSearch in `README.md` (intro, features, architecture diagram, dependencies table, prerequisites, `.env` example, admin UI table)
- Confirmed `docker-compose.yml` already used `opensearchproject/opensearch` — no changes needed
- Replaced `elasticsearch==8.11.0` with `opensearch-py==2.4.2` in `requirements.txt`
- Removed `nutch_data/`, `src/`, and `tests/` directories
- Created full repo directory structure aligned to design doc: `flask_app/`, `celery_worker/`, `mcp_server/`, `nginx/`, `nutch/`, `config/`, `tests/`
- Created `flask_app/__init__.py` — app factory, registers auth/search/admin blueprints
- Created `flask_app/config.py` — all service endpoints and feature flags from environment variables
- Created `flask_app/models/` — `user.py`, `search_history.py`, `crawler_target.py`, `crawl_job.py`
- Created `flask_app/routes/` — `auth.py`, `search.py`, `admin.py` with stub route handlers
- Created `flask_app/services/` — `opensearch.py`, `ollama.py`, `nutch.py` with doc-only stubs
- Created `flask_app/templates/` — `base.html`, `search.html`, `login.html`, `register.html`, `settings.html`, `admin/{index,targets,jobs,config}.html`
- Created `flask_app/static/css/` and `static/js/` with `.gitkeep`
- Created `celery_worker/app.py` — Celery instance with Redis broker
- Created `celery_worker/tasks/crawl.py`, `index.py`, `vectorize.py` — stub Celery tasks
- Created `mcp_server/main.py` — post-MVP placeholder with deferred prerequisites documented
- Created `nginx/nginx.conf` — TLS termination and Flask proxy
- Created `nutch/nutch-site.xml` — TLS override config template
- Created `config/crawler.example.yaml` — example crawler config matching design doc §6
- Created `init.sh` — empty placeholder script
- Reformatted all Python files to match `base.py` standard (module docstring with Author/Date/Email/Description, `# Imports` / `# Globals` / `# Functions` section comments, per-function Input/Output/Details docstrings, `if __name__ == "__main__"` guard)
- Fixed import order: stdlib before third-party in `celery_worker/app.py` and `flask_app/models/user.py`
- Created `TODO.md` — 86 tasks across 15 epics with one-layer-deep `Requires:` dependencies

## Decisions
- Used `opensearch-py==2.4.2` as the drop-in replacement for the Elasticsearch client; API surface is near-identical for basic index/search operations
- Kept `base.py` in the repo root — it is the code style template, not an application file
- Stub route and task functions retain named parameters (e.g. `target_id`) even though the linter flags them as unused — suppressing with `_` prefix would break Flask URL routing
- `mcp_server/` was scaffolded but marked post-MVP throughout; all prerequisites are noted in the file header
- OpenSearch field type for embeddings noted as `knn_vector` in `services/opensearch.py` (not `dense_vector`, which is Elasticsearch-specific)

## Blockers
- None

## Next
- Create Python virtual environment and install `requirements.txt` (Epic 1)
- Add Redis service to `docker-compose.yml` (Epic 2 — unblocks Flask, Celery worker, and Beat services)
- Set up Flask-Migrate with the app factory (Epic 3)

---
session: 2026-03-24T23:44
status: complete
---
## Done
- Audited repo for exposed secrets: found hardcoded `OPENSEARCH_INITIAL_ADMIN_PASSWORD`, MariaDB root and user passwords, and curl `-u admin:<password>` in healthcheck — all in `docker-compose.yml`
- Replaced all hardcoded credentials in `docker-compose.yml` with `${VAR}` environment variable references
- Fixed healthcheck to use `$$OPENSEARCH_INITIAL_ADMIN_PASSWORD` (shell expansion inside container)
- Created `.env.example` with all required vars and blank secret fields
- Scrubbed all secret strings from full git history using `git filter-repo --replace-text`
- Force-pushed rewritten history to `origin/main`

## Decisions
- OpenSearch password (`Gr@nite7Flux!`) was a test credential chosen because the service rejected simple passwords like `password123!` — not a production secret; rotation is still recommended as a precaution since it was publicly visible in git history
- Used `REDACTED` as the replacement string in rewritten history blobs (not an empty string) so the placeholder is visually obvious if anyone inspects old objects
- `example_root_password` and `example_password` were placeholder values but were replaced regardless — GitGuardian flags on field name + value proximity, not value strength

## Blockers
- none

## Next
- Rotate `OPENSEARCH_INITIAL_ADMIN_PASSWORD` in local `.env` before starting the stack
- Open GitHub Support ticket to request purge of cached diff/blob views for old commit SHAs
- Delete any GitHub Actions run logs that may have printed environment variables
- Continue Epic 1: create Python virtual environment and install `requirements.txt`
