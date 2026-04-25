# SHSE — Docker Compose

## Service Overview

| Service | Image | Purpose |
|---|---|---|
| `opensearch` | `opensearchproject/opensearch:latest` | Full-text and vector search index |
| `mariadb` | `mariadb:11` | Relational database (users, history, jobs) |
| `redis` | `redis:7-alpine` | Celery broker and result backend |
| `nutch` | `apache/nutch:latest` | Web crawler |
| `flask` | `Dockerfile.flask` | Web application and REST API |
| `celery_worker` | `Dockerfile.celery` | Async task execution |
| `celery_beat` | `Dockerfile.celery` | Scheduled task dispatcher |
| `nginx` | `nginx:1.27-alpine` | TLS termination and reverse proxy |

### Test-only services

The following services are gated behind a Docker Compose profile and are **not started** during a normal `docker compose up`. Start them explicitly when needed.

| Service | Profile | Image | Purpose |
|---|---|---|---|
| `kiwix` | `test` | `ghcr.io/kiwix/kiwix-serve:latest` | Wikipedia ZIM server for end-to-end crawl testing |

```bash
# Start the Kiwix test server
docker compose --profile test up kiwix -d

# Stop it
docker compose --profile test down kiwix
```

The Kiwix server serves `wikipedia_en_100_nopic_2026-04.zim` (100 Wikipedia articles) at `http://localhost:8082`. Add it as a `type: service` crawler target to test the full indexing pipeline.

## Health Check Configuration

Each service with a standard probe endpoint has a `healthcheck` block.
`celery_worker` and `celery_beat` are exempt: Celery workers expose no HTTP/TCP probe;
their liveness is observable via Redis queue depth.

| Service | Probe |
|---|---|
| `opensearch` | `curl` HTTPS admin endpoint |
| `mariadb` | `healthcheck.sh --connect --innodb_initialized` |
| `redis` | `redis-cli ping` |
| `nutch` | `pgrep -f tail` (process alive check) |
| `flask` | `curl` HTTP health endpoint |
| `nginx` | `curl` HTTP port 80 |

## Startup Order

Dependencies enforced via `depends_on` with `condition: service_healthy`:

```
opensearch ─┐
mariadb    ─┼─→ flask ─────────────→ nginx
redis      ─┘
            └─→ celery_worker
            └─→ celery_beat
opensearch ─→ nutch
```

Services will not start until their dependencies report healthy.
On first boot, `opensearch` and `mariadb` take the longest to initialise (up to 40–60 s).

## How to Run the Stack

1. Configure `.env` (see `docs/setup.md`).

2. Start all services in the background:
   ```bash
   docker compose up -d
   ```

3. Confirm all services are healthy:
   ```bash
   bash init.sh
   ```

4. Access the application:
   - HTTP (redirects to HTTPS): `http://localhost:8888`
   - HTTPS: `https://localhost:8443`

5. Stop the stack:
   ```bash
   docker compose down
   ```

6. Destroy volumes (full reset, **deletes all data**):
   ```bash
   docker compose down -v
   ```
