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
