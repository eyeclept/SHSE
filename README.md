# Self-Hosted Search Engine (SHSE)

**SHSE** is a private, homelab-native search engine. It indexes and searches the services, pages, and content running on your internal network — not the public internet. Full-text BM25 retrieval via OpenSearch, link-following BFS crawling, optional AI summaries and semantic search via any OpenAI-compatible LLM endpoint, and inline answer cards that resolve common queries without leaving the search page.

Admins define what gets crawled via a YAML config file or the admin UI, schedule indexing jobs that run automatically via Celery Beat, and control the index from the admin UI or the CLI. Users get a clean search interface with AI-assisted result summaries, semantic matches, inline answer cards, and suggested keyword chips — all backed entirely by infrastructure you control.

---

## Features

### Search
- **Full-text search** — BM25 multi-field retrieval via OpenSearch with typo tolerance (`fuzziness: AUTO`)
- **Hybrid search** — BM25 and vector results fused via Reciprocal Rank Fusion (RRF); BM25 renders immediately while vector results load async via HTMX
- **Semantic search** — Local embeddings via any OpenAI-compatible endpoint (Ollama, LiteLLM, vLLM); falls back silently to BM25 when the LLM API is unavailable
- **AI query rewriter** — Optional lightweight model rewrites conversational queries into terse search terms before hitting OpenSearch
- **Google-style dork operators** — `site:`, `inurl:`, `intitle:`, `filetype:`, `"exact phrase"`, `-exclude`
- **Search filters** — Filter by service (source) and content type; sort by relevance, newest, or oldest
- **Query preprocessing** — Preamble stripping, normalisation, stopword removal, synonym expansion
- **Suggested keywords** — Post-search keyword chips extracted from semantic results to refine queries

### Inline Answer Cards
Answer cards appear above BM25 results when the query matches a known pattern:

| Card | Trigger | Backend |
|---|---|---|
| Dictionary | word definitions, "define X" | StarDict/OED files (offline) |
| Date & time | "what time is it", "what day is…" | NTP or system clock |
| Weather | "weather", "temperature", "forecast" | Home Assistant / InfluxDB / Open-Meteo / NWS (priority chain) |
| Calculator | arithmetic expressions (`2^10 + 4`) | AST-safe evaluator |
| Unit converter | `"25 km to miles"`, `"100 F to C"` | Built-in factor table |
| Translation | `"translate … to French"` | Ollama (aya-expanse:8b or configurable) |

All card results are injected as context when an AI summary is generated.

### Crawling & Indexing
- **BFS web crawling** — Link-following crawl from a seed URL to configurable depth, per-target in YAML or the admin UI
- **Flexible ingestion** — Service crawl, subnet scan, OAI-PMH harvest, RSS/Atom feed, or custom API adapter
- **Auto-vectorization** — Embeddings backfilled automatically after each successful crawl when the LLM API is configured
- **Scheduled indexing** — Cron-style per-target schedules managed by Celery Beat with Redis-backed persistence (redbeat)
- **Job tracking** — Crawl and vectorize jobs visible in Admin → Jobs with live HTMX polling

### AI
- **AI summaries** — RAG-generated answers above BM25 results; enabled/disabled globally by admin, per-user toggle available; requires LLM API
- **Fallback embeddings** — CPU-based sentence-transformers embedding when LLM API is down; semantic rail stays functional

### Authentication & Accounts
- **Local auth** — bcrypt passwords; default admin account bootstrapped on first boot
- **Two-factor authentication** — TOTP (Aegis, Bitwarden, Google Authenticator) and FIDO2/WebAuthn hardware keys (YubiKey, SoloKey); both optional and independent
- **Email password recovery** — Forgot-password flow via self-hosted SMTP (Postfix, Mailcow); disabled when `SMTP_HOST` is blank
- **SSO** — Optional OIDC integration (Authentik, Keycloak, Authelia); role mapped from the `groups` claim; local auth can be kept alongside or disabled
- **Per-user search history** — Stored in MariaDB; clearable from Settings
- **Role-based access** — `admin` (full access) and `user` (search + history)
- **Rate limiting** — Login endpoint limited to 10 requests per minute per IP

### Admin & Operations
- **Admin UI** — Health dashboard, crawl target management, YAML import/export, index operations, user promotion/demotion
- **Admin CLI** — `cli.py` for stats, search, crawl dispatch, config upload, admin password recovery, job history
- **System reset** — `bash reset.sh` wipes all persistent state and restores a clean install
- **MCP server** — Optional FastAPI server exposing a `search_lab` tool for AI assistant integrations
- **systemd integration** — Auto-start on boot via `systemd/shse.service`

### Security
- CSRF tokens on all state-changing forms (Flask-WTF)
- Session cookies: `HttpOnly`, `SameSite=Lax`, `Secure` in production; 24-hour expiry
- Login rate limiting: 10 requests per minute per IP (Flask-Limiter)
- Redis and MariaDB bound to `127.0.0.1` (not exposed to network interfaces)
- TLS 1.2+ enforced at Nginx (`ssl_protocols TLSv1.2 TLSv1.3`)

---

## Architecture

```mermaid
graph TD
    User([User / Browser]) -->|HTTPS| Nginx
    Nginx -->|proxy| Flask["Flask\n(Web UI + REST API)"]

    Flask --> MariaDB[(MariaDB\nusers · jobs · config)]
    Flask --> OpenSearch[(OpenSearch\nsearch index + vectors)]
    Flask --> Redis[(Redis\nbroker + Beat state)]

    Redis --> Worker[Celery Worker]
    Redis --> Beat[Celery Beat\nscheduled crawls]

    Worker -->|BFS crawl| Target["Target Services\n(HTTP/HTTPS)"]
    Worker -->|index docs| OpenSearch
    Worker -->|vectorize| LLM["LLM API\n(optional)\nOllama · LiteLLM · vLLM"]

    Flask -->|embed + search| LLM
    Flask -->|semantic query| OpenSearch

    Beat -->|dispatch| Worker

    Nutch["Apache Nutch\nREST server"] -.->|crawldb state| Worker
```

### Services

| Service | Role | Required |
|---|---|---|
| OpenSearch | Search index + vector store | Yes |
| MariaDB | Users, history, crawler config, job tracking | Yes |
| Redis | Celery task broker + Beat schedule persistence | Yes |
| Apache Nutch | Web crawler (REST server, auto-starts) | Yes |
| LLM API | Embeddings, AI summaries, semantic search, translation | No |
| Nginx | Reverse proxy / TLS termination | Recommended |
| SSO Provider | OIDC authentication | No |
| SMTP Server | Email password recovery | No |

---

## Minimum Hardware Requirements

SHSE figures are **measured minimums** from `docker stats` on an idle deployed stack. Third-party service requirements (OpenSearch, MariaDB, Redis, Nutch, Ollama) change over time — check each project's documentation for current figures before planning hardware.

SHSE can run on a single machine or split across VMs. The reference deployment uses three VMs; specs for each are in [Section 4](#4-multi-vm-reference-deployment).

---

### 1. SHSE Application

| Container | Min RAM | Notes |
|---|---|---|
| Flask (web UI + API) | ~126 MiB | |
| Celery Worker | ~231 MiB | No embedded model — CPU embedding fallback is opt-in (see `requirements-cpu-fallback.txt`) |
| Celery Beat (scheduler) | ~123 MiB | |
| Nginx (reverse proxy) | ~4 MiB | |
| **SHSE minimum** | **~484 MiB** | |

> **CPU embedding fallback:** `sentence-transformers` and PyTorch (~6 GB installed) are not included in the Docker image by default. If you need semantic search to keep working when the LLM API is down, install `requirements-cpu-fallback.txt` and set `cpu_fallback = true` in `config.ini [llm]`. The Celery Worker will then use ~1.2 GiB instead of ~231 MiB.

---

### 2. Required and Optional Services

> **These figures reflect current versions at time of writing. Requirements for third-party services change with each release.** Check upstream documentation before provisioning hardware:
> - OpenSearch: [opensearch.org/docs](https://opensearch.org/docs/latest/) — [GitHub](https://github.com/opensearch-project/OpenSearch)
> - Apache Nutch: [nutch.apache.org](https://nutch.apache.org/) — [GitHub](https://github.com/apache/nutch)
> - MariaDB: [mariadb.org/documentation](https://mariadb.org/documentation/) — [GitHub](https://github.com/MariaDB/server)
> - Redis: [redis.io/docs](https://redis.io/docs/) — [GitHub](https://github.com/redis/redis)
> - Ollama: [ollama.com](https://ollama.com) — [GitHub](https://github.com/ollama/ollama)
| Service | Min RAM | Notes |
|---|---|---|
| OpenSearch | ~1.7 GiB | JVM heap set to 1 GiB (`-Xms1g -Xmx1g`); raise for large indexes, lower for constrained hosts |
| Nutch | ~196 MiB | JVM-based; REST server mode |
| MariaDB | ~180 MiB | |
| Redis | ~28 MiB | |
| **Required services minimum** | **~2.1 GiB** | |
| | | |
| **Ollama — optional LLM host** | | |
| Daemon process | ~206 MiB RAM | Host process; no models loaded |
| + nomic-embed-text | +~270 MiB VRAM | Embedding; kept loaded between requests |
| + granite4.1:3b (query rewriter) | +~2.0 GiB VRAM | Unloads after ~5 min idle |
| + granite4.1:8b (AI summaries) | +~5.0 GiB VRAM | Unloads after ~5 min idle |
| + aya-expanse:8b (translation) | +~4.7 GiB VRAM | Unloads after ~5 min idle |

> Ollama does not load all models simultaneously. Peak VRAM is the embedding model (~270 MiB, kept warm) plus whichever generative model is active (~5 GiB). Models are configurable — swap any for lighter or heavier variants as hardware allows.

> **CPU-only Ollama:** Move the VRAM figures above into RAM. `nomic-embed-text` is fast on CPU; generation models are 10–50× slower and memory-intensive.

---

### 3. Combined Minimums (single machine)

| Configuration | Min RAM | Min VRAM |
|---|---|---|
| BM25 only (no LLM) | **~2.6 GiB** | None |
| Embedding + semantic search | **~2.6 GiB** | ~300 MiB |
| Embedding + AI summaries *(recommended)* | **~2.6 GiB** | ~5.5 GiB |
| Full AI (summaries + rewrite + translation) | **~2.6 GiB** | ~5.5 GiB peak |
| Full AI, CPU-only (no GPU) | **~8 GiB** | None |

Peak VRAM is the embedding model plus one generative model at a time; Ollama unloads idle models after ~5 minutes.

**Quick reference:**
- **3 GiB RAM** minimum — BM25 only, no AI
- **4 GiB RAM** minimum — full stack with GPU-backed LLM
- **8 GiB RAM** minimum — full stack with CPU-only LLM
- **6 GiB VRAM** minimum — embedding + AI summaries (RTX 3060 12 GB class)
- **12 GiB VRAM** recommended — all default models with headroom

---

### 4. Multi-VM Reference Deployment

The reference deployment splits services across three VMs. All figures are measured from the running stack.

| VM | Role | Min RAM | Min Disk | Notes |
|---|---|---|---|---|
| SHSE App | Flask, Celery, Nginx | **4 GiB** | **50 GiB** | ~14 GiB used (Docker images + OS); 4 GiB gives comfortable headroom |
| SHSE Services | OpenSearch, MariaDB, Redis, Nutch | **6 GiB** | **50 GiB** | OpenSearch dominates at ~1.7 GiB; 6 GiB allows index growth |

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

2. Copy the secrets template and fill in required values:
   ```bash
   cp .env.example .env
   ```
   ```ini
   # .env — secrets only
   SECRET_KEY=<strong-random-string>
   MARIADB_PASSWORD=<your-db-password>
   MARIADB_ROOT_PASSWORD=<your-root-password>
   OPENSEARCH_INITIAL_ADMIN_PASSWORD=<Min8Chars1Special!>
   ```
   All other configuration (hosts, ports, models, feature flags) lives in `config.ini`, which is checked into git and has sensible local defaults.

3. (Optional) Edit `config.ini` for non-default values — for example, to point at an existing Ollama instance:
   ```ini
   [llm]
   api_base    = http://192.168.1.50:11434/v1
   embed_model = nomic-embed-text
   gen_model   = granite4.1:8b
   ```

4. Start the stack:
   ```bash
   docker compose up -d
   ```

5. Confirm all services are healthy:
   ```bash
   bash init.sh
   ```

6. Log in at `https://localhost:8443` with the default admin credentials:
   - **Username:** `admin`
   - **Password:** `admin`

   You will be redirected to Settings and prompted to change the password on first login.

See [docs/installGuide.md](docs/installGuide.md) for the full step-by-step guide and [docs/docker.md](docs/docker.md) for service details.

---

## Configuration

SHSE separates concerns between two files:

| File | Contains | Git-tracked |
|---|---|---|
| `.env` | Secrets only (passwords, keys, tokens) | No — never commit |
| `config.ini` | Everything else (hosts, ports, models, flags) | Yes |

Docker services override specific `config.ini` values via their `environment:` blocks (e.g. `MARIADB_HOST=mariadb` inside the compose network overrides `config.ini [mariadb] host = localhost`).

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
    crawl_depth: 2      # BFS link hops from seed URL (0 = seed page only)
    tls_verify: false   # set false for self-signed certs

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

# Crawler config
python cli.py upload-config config/crawler.example.yaml
python cli.py list-targets

# Crawl operations (dispatches to Celery worker)
python cli.py crawl myblog
python cli.py crawl-all

# Index operations
python cli.py vectorize
python cli.py wipe-index --yes

# Job history
python cli.py jobs

# Admin password recovery (server-side; no current password required)
python cli.py reset-admin-password admin
```

---

## Search API

### `GET /api/search`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `q` | string | `""` | Search query (dork operators supported) |
| `page` | int | `1` | Page number (1-indexed) |
| `tab` | string | `"all"` | Content tab filter |
| `filter_service` | string (repeatable) | — | Restrict to named service(s) |
| `sort` | string | `"relevance"` | `relevance` / `newest` / `oldest` |

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
      "title": "Nginx - My Homelab Docs",
      "url": "http://docs.homelab.lan/nginx",
      "service": "homelab-docs",
      "port": 80,
      "crawled_at": "2026-04-25",
      "snippet": "Nginx is a web server that can also be used as a reverse proxy…",
      "vectorized": true
    }
  ],
  "sources": [{ "name": "homelab-docs", "n": 42 }]
}
```

### `GET /api/stats`

```json
{ "docs": 14021, "services": 6, "last_crawl": "2026-04-25T10:00:00" }
```

---

## Authentication

### Local auth (default)

Username and bcrypt-hashed password stored in MariaDB. A default admin account (`admin` / `admin`) is created automatically on first boot; you are prompted to change it on first login.

### Two-factor authentication

Users can enroll a TOTP authenticator app (Aegis, Bitwarden, etc.) or a FIDO2 hardware security key (YubiKey, SoloKey) from the Settings page. Both methods are optional and independent.

### Email password recovery

When `SMTP_HOST` is configured, a "Forgot password?" link appears on the login page. Password reset tokens expire after one hour. Works with any self-hosted SMTP server (Postfix, Mailcow, etc.).

### SSO via OIDC (optional)

Set `SSO_ENABLED = true` in `config.ini [sso]` and set `SSO_CLIENT_SECRET` in `.env`. Any OIDC-compatible provider works (Authentik, Keycloak, Authelia). User roles are mapped from the OIDC `groups` claim: members of `SSO_ADMIN_GROUP` (default `admin`) receive the admin role.

See [docs/auth.md](docs/auth.md) for the full route reference and SSO configuration guide.

---

## Roles

| Role | Permissions |
|---|---|
| `admin` | Search, history, full access to `/admin` (health, targets, jobs, config, users) |
| `user` | Search, own search history, Settings |

---

## Semantic Search and AI Features

When a compatible LLM API is configured (`[llm] api_base` in `config.ini`):

1. BM25 results render immediately
2. An HTMX request fires for `/api/semantic` — vector results and suggested keyword chips load in the right rail without blocking
3. An AI summary (RAG-generated answer) is shown above BM25 results when the admin has enabled it

The admin can enable/disable AI summaries globally and choose the models from Admin → Config. Users can toggle AI summaries individually from Settings.

If the LLM API is unreachable, SHSE falls back to BM25-only results without error. CPU-based embeddings (sentence-transformers) are used as a fallback for vector search when the LLM API is down.

---

## Docs

| File | Contents |
|---|---|
| [docs/installGuide.md](docs/installGuide.md) | Step-by-step installation from scratch |
| [docs/usageGuide.md](docs/usageGuide.md) | Day-to-day usage: searching, crawling, admin, CLI |
| [docs/setup.md](docs/setup.md) | config.ini and .env reference; Docker prerequisites |
| [docs/docker.md](docs/docker.md) | Service overview, healthchecks, startup order |
| [docs/guide.md](docs/guide.md) | Operator guide: first run, YAML config, test server setup |
| [docs/config.md](docs/config.md) | YAML crawler config format and field reference |
| [docs/auth.md](docs/auth.md) | Auth routes, 2FA, SSO, session lifecycle |
| [docs/database.md](docs/database.md) | Schema, migrations, ERD |
| [docs/opensearch.md](docs/opensearch.md) | Index schema, query shapes, chunking, idempotent upsert |
| [docs/tasks.md](docs/tasks.md) | Celery task signatures, Beat schedule, CrawlJob lifecycle |
| [docs/llm.md](docs/llm.md) | LLM API integration, embedding, RAG flow, fallback |
| [docs/search_quality.md](docs/search_quality.md) | Query preprocessing, synonym expansion, hybrid RRF search |
| [docs/query_rewriter.md](docs/query_rewriter.md) | AI query rewriter: configuration and toggle |
| [docs/search_filters.md](docs/search_filters.md) | Filter by service and content type; sort options |
| [docs/dorking.md](docs/dorking.md) | Google-style dork operators |
| [docs/dictionary.md](docs/dictionary.md) | StarDict/OED dictionary answer card |
| [docs/datetime_cards.md](docs/datetime_cards.md) | Date and time answer cards |
| [docs/weather_cards.md](docs/weather_cards.md) | Weather answer cards (HA, InfluxDB, Open-Meteo, NWS) |
| [docs/calculator.md](docs/calculator.md) | Calculator answer card |
| [docs/unit_converter.md](docs/unit_converter.md) | Unit converter answer card |
| [docs/translate.md](docs/translate.md) | Offline translation answer card |
| [docs/search_ui.md](docs/search_ui.md) | Search routes, semantic rail, keyword chips |
| [docs/admin_ui.md](docs/admin_ui.md) | Admin routes, health checks, job management, YAML upload |
| [docs/tls.md](docs/tls.md) | Per-target TLS bypass, global flag, warning banner |
| [docs/nginx.md](docs/nginx.md) | Proxy config, SSL cert setup, `/admin/*` restriction |
| [docs/nutch.md](docs/nutch.md) | Nutch REST API reference, TLS patch |
| [docs/mcp.md](docs/mcp.md) | MCP server: search_lab tool for AI assistant integrations |
| [docs/systemd.md](docs/systemd.md) | Auto-start on boot via systemd |
| [docs/testing.md](docs/testing.md) | Running tests, fixture overview, Playwright E2E |
| [docs/security_review.md](docs/security_review.md) | Security audit findings and remediation status |

---

## License

MIT
