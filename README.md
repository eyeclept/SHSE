# Self-Hosted Search Engine (SHSE)

> ⚠️ **This project is currently in active development. The backend is complete; the admin and search UI are in progress.**

**SHSE** is a private, homelab-native search engine. It indexes and searches the services, pages, and content running on your internal network — not the public internet. Built around OpenSearch for full-text BM25 retrieval and Apache Nutch for network crawling, with optional support for a local LLM API (Ollama, LiteLLM, or any OpenAI-compatible endpoint) for AI-generated summaries.

Admins define what gets crawled via a YAML config file, schedule indexing jobs that run automatically via Celery Beat, and control the index from the admin UI or the CLI. Users get a clean search interface with optional AI-assisted result summaries — all backed entirely by infrastructure you control.

---

## Features

- **Full-text search** — BM25 retrieval via OpenSearch across all indexed homelab content
- **JSON search API** — `GET /api/search` for programmatic access; no HTML parsing required
- **AI summaries** — Optional RAG-based summaries via any OpenAI-compatible LLM endpoint
- **Flexible crawling** — Crawl subnets, specific services, OAI-PMH repositories, RSS/Atom feeds, or push via custom adapters
- **Scheduled indexing** — Cron-style crawl schedules per target, managed by Celery Beat; loaded automatically from the YAML config at worker startup
- **Admin CLI** — `python cli.py` for managing the index, crawls, and config without the browser
- **User accounts** — Per-user search history; role-based access (admin vs. user)
- **SSO support** — Optional OIDC integration (Authentik, Keycloak, Authelia); local password auth on by default

---

## Architecture

```
User ──HTTPS──▶ Nginx ──▶ Flask (Web UI + REST API)
                              │
                    ┌─────────┼─────────┐
                    ▼         ▼         ▼
                MariaDB   OpenSearch   Redis
             (users/jobs) (index)    (broker)
                                        │
                              ┌─────────┴─────────┐
                              ▼                   ▼
                        Celery Worker        Celery Beat
                              │              (schedules)
                              ▼
                        Apache Nutch
                        (web crawler)
                              │
                              ▼
                    OpenSearch (index)
                              │
                      LLM API (optional)
                     (embeddings + RAG)
```

### Dependencies

| Service | Role | Required |
|---|---|---|
| OpenSearch | Search index + vector store | Yes |
| MariaDB | Users, history, crawler config | Yes |
| Redis | Celery task broker | Yes |
| Apache Nutch | Web crawler | Yes |
| LLM API | Embeddings + AI summaries | No |
| Nginx | Reverse proxy / TLS termination | Recommended |
| SSO Provider | OIDC authentication | No |

---

## Getting Started

### Prerequisites

- Docker 24+ and Docker Compose v2
- Git

### Quick Start

1. Clone the repository:
   ```bash
   git clone https://github.com/youruser/shse.git
   cd shse
   ```

2. Copy and edit the environment file:
   ```bash
   cp .env.example .env
   ```

3. Fill in required secrets in `.env`:
   ```ini
   SECRET_KEY=change-me-to-a-random-string
   MARIADB_PASSWORD=your-db-password
   MARIADB_ROOT_PASSWORD=your-root-password
   OPENSEARCH_INITIAL_ADMIN_PASSWORD=Min8Chars1Special!
   ```

4. (Optional) Configure the LLM API for AI summaries:
   ```ini
   LLM_API_BASE=http://192.168.1.50:11434/v1
   LLM_EMBED_MODEL=nomic-embed-text
   LLM_GEN_MODEL=llama3
   ```

5. Start the stack:
   ```bash
   docker compose up -d
   ```

6. Confirm all services are healthy:
   ```bash
   bash init.sh
   ```

7. Navigate to `http://localhost:8888/setup` to create the initial admin account.

See [docs/setup.md](docs/setup.md) for full setup instructions and [docs/docker.md](docs/docker.md) for service details.

---

## Crawler Configuration

Crawl targets are defined in a YAML file uploaded via the admin UI or the CLI.

```yaml
defaults:
  service: http
  port: 80
  route: /
  tls_verify: true
  schedule:
    frequency: weekly
    day: sunday
    time: "02:00"
    timezone: UTC

targets:
  - type: service
    nickname: myblog
    url: blog.homelab.lan
    port: 80
    tls_verify: false        # set false for self-signed certs

  - type: network
    network: 192.168.1.0/24

  - type: oai-pmh
    nickname: invenio
    url: invenio.lab.internal
    endpoint: /oai2d

  - type: feed
    nickname: ghost-blog
    url: blog.lab.internal
    feed_path: /rss

  - type: api-push
    nickname: discourse-api
    url: discourse.lab.internal
    adapter: discourse_adapter
```

Any field omitted from a target inherits from the `defaults` block. See [docs/config.md](docs/config.md) for the full field reference.

---

## CLI

`cli.py` provides direct access to every admin operation from the terminal. Requires the Docker stack to be running.

```bash
# Index stats
python cli.py stats

# Search
python cli.py search "nginx reverse proxy"
python cli.py search "homelab" --page 2

# Crawler config
python cli.py upload-config config/crawler.example.yaml
python cli.py list-targets

# Crawl operations (dispatches to Celery worker)
python cli.py crawl myblog
python cli.py crawl-all
python cli.py reindex myblog
python cli.py reindex-all --yes

# Index operations
python cli.py vectorize
python cli.py create-index
python cli.py wipe-index --yes

# Job history
python cli.py jobs
python cli.py jobs --limit 50
```

---

## Search API

SHSE exposes a JSON REST API for programmatic search access.

### `GET /api/search`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `q` | string | `""` | Search query |
| `page` | int | `1` | Page number (1-indexed) |
| `tab` | string | `"all"` | Content tab filter |

**Response:**
```json
{
  "q": "nginx",
  "total": 42,
  "took_ms": 8,
  "page": 1,
  "page_count": 5,
  "results": [
    {
      "id": "abc123",
      "title": "Nginx — My Homelab Docs",
      "url": "http://docs.homelab.lan/nginx",
      "service": "homelab-docs",
      "port": 80,
      "crawled_at": "2026-04-25T10:00:00",
      "snippet": "Nginx is a web server that can also be used as a reverse proxy…",
      "vectorized": true
    }
  ],
  "sources": [
    { "name": "homelab-docs", "n": 42 }
  ]
}
```

Returns 200 with empty `results` on any OpenSearch failure.

### `GET /api/stats`

Returns document count, service count, and last crawl timestamp.

```json
{ "docs": 14021, "services": 6, "last_crawl": "2026-04-25T10:00:00" }
```

---

## Authentication

### Local auth (default)

Username and bcrypt-hashed password stored in MariaDB. No configuration required. The first admin account is created at `/setup` on first run.

### SSO via OIDC (optional)

Set `SSO_ENABLED=true` and configure your provider in `.env`. Any OIDC-compatible provider works. User roles are mapped from the OIDC `groups` claim: members of `SSO_ADMIN_GROUP` (default `admin`) receive the admin role.

See [docs/auth.md](docs/auth.md) for the full route reference and SSO configuration guide.

---

## Roles

| Role | Permissions |
|---|---|
| `admin` | Search, view history, full access to `/admin` |
| `user` | Search, view own history |

---

## AI Summaries

When a compatible LLM API is configured (`LLM_API_BASE`), SHSE performs hybrid retrieval at query time: BM25 results are returned immediately while a vector search gathers context chunks for the generative model. The summary appears as a collapsible card above the standard results.

AI summaries can be toggled per-user in settings. If the LLM API is unreachable, SHSE falls back to BM25-only results without error.

### Deferred vectorization

If the LLM API is unavailable during indexing, documents are stored with `vectorized=false`. Once the API is reachable again, run:

```bash
python cli.py vectorize
```

This backfills embeddings across the entire index. Also useful when switching embedding models.

See [docs/llm.md](docs/llm.md) for the full API reference.

---

## Docs

| File | Contents |
|---|---|
| [docs/setup.md](docs/setup.md) | Installation, environment config, Docker prerequisites |
| [docs/docker.md](docs/docker.md) | Service overview, healthchecks, startup order |
| [docs/guide.md](docs/guide.md) | End-user and operator guide: first run, crawling, searching |
| [docs/config.md](docs/config.md) | YAML crawler config format and field reference |
| [docs/auth.md](docs/auth.md) | Auth routes, session lifecycle, SSO configuration |
| [docs/database.md](docs/database.md) | Schema, migrations, ERD |
| [docs/opensearch.md](docs/opensearch.md) | Index schema, query shapes, chunking, idempotent upsert |
| [docs/tasks.md](docs/tasks.md) | Celery task signatures, Beat schedule, CrawlJob lifecycle |
| [docs/llm.md](docs/llm.md) | LLM API integration, embedding, RAG flow, fallback |
| [docs/nutch.md](docs/nutch.md) | Nutch REST API reference, crawl pipeline, TLS |

---

## License

MIT
