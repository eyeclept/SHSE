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
