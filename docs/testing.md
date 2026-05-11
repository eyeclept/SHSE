# SHSE - Testing

---

## How to Run Tests

All tests live in `tests/`. Run the full suite from the project root:

```bash
.venv/bin/pytest tests/
```

Quick pass (no output on success):

```bash
.venv/bin/pytest tests/ -q
```

Run a specific file:

```bash
.venv/bin/pytest tests/test_opensearch.py -v
```

Run a specific test:

```bash
.venv/bin/pytest tests/test_opensearch.py::test_bm25 -v
```

---

## Test Files

| File | Coverage | Requires live stack |
|---|---|---|
| `test_setup.py` | venv, requirements imports, init.sh | Docker (init.sh) |
| `test_compose.py` | docker-compose.yml validity and service definitions | Docker |
| `test_db.py` | All four tables, schema, FK enforcement | MariaDB |
| `test_auth.py` | Login, logout, register, setup, SSO, RBAC, theme toggle | No |
| `test_opensearch.py` | Index schema, BM25, chunking, idempotent upsert, vector search, management ops | No |
| `test_nutch.py` | Crawl pipeline, TLS patch, fetch results, page text extraction | No |
| `test_llm.py` | Embedding, summary, fallback on error | No |
| `test_yaml.py` | YAML parsing, defaults, all target types, Beat entries, DB persistence | No |
| `test_tasks.py` | All Celery tasks, CrawlJob lifecycle, Beat schedule loading | No |
| `test_api.py` | `/api/search`, `/api/stats`, `/api/semantic`, `/api/admin-check` | No |
| `test_search_routes.py` | Home page, results, history write | No |
| `test_search_ui.py` | Search route BM25, AI summary (shown/hidden), history page, auth pages | No |
| `test_admin.py` | Dashboard, health checks, config upload, jobs, action buttons | No |
| `test_nginx.py` | nginx.conf structure, admin-check endpoint, live proxy (skip if down) | Nginx (live tests) |
| `test_kiwix.py` | Kiwix server content, article access, 404 handling | Kiwix (`--profile test`) |
| `test_playwright.py` | End-to-end UI: home page, search, login/logout, history, admin panel, sort, filter | Full stack + Playwright |

---

## Playwright Integration Tests

### Prerequisites

```bash
pip install pytest-playwright
playwright install chromium
docker compose up -d          # full stack must be running
./rebuild.sh                  # if flask_app/ code changed since last build
```

### Run Playwright tests only

```bash
.venv/bin/pytest tests/test_playwright.py -v
```

All Playwright tests skip automatically when `http://localhost:5000` is not reachable.

### Search query note

Playwright scenarios use `"human anatomy"` and `"cell biology"` as test queries.
These return results from the default Kiwix Wikipedia crawl target
(`http://172.27.72.16:8082/content/wikipedia_en_100_nopic_2026-04/index`, depth 7).
If the index is empty, result-dependent tests skip with a clear message.

### Seeded test accounts

`tests/conftest.py` creates two test accounts before the session and removes them after:

| Account | Role | Created via |
|---|---|---|
| `pw_test_admin` | admin | Direct MariaDB INSERT |
| `pw_test_user` | user | HTTP POST `/register` |

---

## Fixture Overview

Most test files share a common fixture pattern:

```python
@pytest.fixture
def app():
    """SQLite in-memory Flask app - no live MariaDB."""
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    db.init_app(flask_app)
    login_manager.init_app(flask_app)
    # register blueprints ...
    with flask_app.app_context():
        db.create_all()
        yield flask_app
```

**Shared conftest fixtures** (available to all test files via `tests/conftest.py`):

| Fixture | Scope | Description |
|---|---|---|
| `base_url` | session | `"http://localhost:5000"` — consumed by pytest-playwright's `page` fixture |
| `test_admin_creds` | session | `{username, password}` for seeded admin; cleaned up after session |
| `test_user_creds` | session | `{username, password}` for seeded regular user |

**Per-module fixtures** (defined inline in each test file):

| Fixture | Description |
|---|---|
| `app` | SQLite in-memory Flask app (no live MariaDB needed) |
| `client` | Flask test client (pytest-flask) |
| `admin_client` | Authenticated Flask test client with admin session |
| `db_session` | SQLAlchemy session against the test DB |

External service calls (OpenSearch, Nutch, LLM API, Celery) are mocked using
`unittest.mock.patch` or `MagicMock`. No live services are required for the
majority of the test suite.

Tests that DO require live services (`test_db.py`, `test_setup.py`,
`test_compose.py`, `test_kiwix.py`) are marked with clear docstrings and will
fail with a connection error when the relevant service is not running.

---

## Coverage Commands

Install `pytest-cov` (not in `requirements.txt` - dev only):

```bash
.venv/bin/pip install pytest-cov
```

Generate a terminal coverage report:

```bash
.venv/bin/pytest tests/ --cov=flask_app --cov=celery_worker --cov-report=term-missing
```

Generate an HTML report:

```bash
.venv/bin/pytest tests/ --cov=flask_app --cov=celery_worker --cov-report=html
open htmlcov/index.html
```

---

## Running Against the Live Stack

Tests that require live services need the Docker stack running:

```bash
docker compose up -d
bash init.sh             # confirm all services healthy
.venv/bin/pytest tests/  # run all tests including live ones
```

For the Kiwix integration tests:

```bash
docker compose --profile test up kiwix -d
.venv/bin/pytest tests/test_kiwix.py -v
```
