# VM Layout

Two VMs run the SHSE stack. They communicate over a shared host-only network.

| VM | IP | Role |
|---|---|---|
| App VM | 172.27.72.56 | Flask, Celery, Nginx |
| Services VM | 172.27.72.57 | MariaDB, OpenSearch, Redis, Mailpit |

---

## App VM (172.27.72.56)

**Codebase:** `~/shse/` — full application source, deployed as a file copy (no `.git`).

**Compose file:** `~/shse/docker-compose.yml` (or `docker-compose.app.yml`)

| Container | Image | Status | Port |
|---|---|---|---|
| flask | shse-flask | healthy | 127.0.0.1:5000 |
| celery_worker | shse-celery_worker | up | — |
| celery_beat | shse-celery_beat | up | — |
| nginx | nginx:1.27-alpine | healthy | 0.0.0.0:80, 0.0.0.0:443 |

**Deployment:** Use `deploy.sh` at the project root to sync code and rebuild containers.

---

## Services VM (172.27.72.57)

**Codebase:** `~/shse/` contains only `docker-compose.services.yml` and `data/`. No application code.

**Compose file:** `~/shse/docker-compose.services.yml`

| Container | Image | Status | Port |
|---|---|---|---|
| mariadb | mariadb:11 | healthy | 172.27.72.57:3306 |
| opensearch | opensearchproject/opensearch:latest | healthy | 172.27.72.57:9200 |
| redis | redis:7-alpine | healthy | 172.27.72.57:6379 |
| mailpit | axllent/mailpit:latest | healthy | 172.27.72.57:1025 (SMTP), 172.27.72.57:8025 (UI) |

All persistent data lives under `~/shse/data/` on this VM.

---

## Cross-VM Connectivity

The app VM reaches services VM by IP. All service clients in `config.ini` must use `172.27.72.57` as the host — not `localhost`. The relevant keys:

```ini
REDIS_HOST     = 172.27.72.57
MARIADB_HOST   = 172.27.72.57
OPENSEARCH_HOST = 172.27.72.57
SMTP_HOST      = 172.27.72.57
```

---

## Startup Order Independence

Epic 26 (graceful startup) was completed to make the stack converge regardless of which VM starts first. The implemented guarantees:

| Mechanism | Status |
|---|---|
| Flask lazy DB connect (no crash on MariaDB unavailable at boot) | passing |
| Flask OpenSearch fallback (search returns empty, no 500) | passing |
| Admin task dispatch Redis error handled (no crash on Redis unavailable) | passing |
| Celery broker retry on startup (`broker_connection_retry_on_startup=True`) | passing |
| Celery task `autoretry_for` wired for transient errors | passing |
| `depends_on` relaxed to `service_started` (not `service_healthy`) | passing |

**Current deviation:** `celery_beat` fails on startup not because of ordering but because its broker URL points to `localhost` instead of `172.27.72.57`. Once OP-001 is resolved, startup-order independence holds for all services.

---

## Deployment Notes

- Neither VM has `git` installed. Code is deployed by rsync from the dev machine.
- App VM codebase was last deployed 2026-05-18. See `Assist/TODO.md` OP-002 for the sync procedure.
- The `.env` file on the app VM holds secrets (e.g., `REDIS_PASSWORD`). It is not in version control and must be maintained manually on the VM.
