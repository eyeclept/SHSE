# SHSE - Project Setup

## Install Steps

1. Clone the repository and enter the project root.

2. Create a Python virtual environment:
   ```bash
   python3 -m venv .venv
   ```

3. Install all dependencies:
   ```bash
   .venv/bin/pip install -r requirements.txt
   ```

4. Verify the installation:
   ```bash
   .venv/bin/pip check
   ```
   Expect: no errors.

## Environment Configuration

1. Copy the template:
   ```bash
   cp .env.example .env
   ```

2. Open `.env` and fill in all values. Required fields:

   | Key | Purpose |
   |---|---|
   | `SECRET_KEY` | Flask session signing key |
   | `MARIADB_PASSWORD` | Application DB user password |
   | `MARIADB_ROOT_PASSWORD` | MariaDB root password |
   | `OPENSEARCH_INITIAL_ADMIN_PASSWORD` | OpenSearch admin password (8+ chars, uppercase, number, special) |

   Leave `MARIADB_HOST`, `REDIS_HOST`, and `OPENSEARCH_HOST` as `localhost` for local development.
   These are overridden to container hostnames inside Docker Compose.

3. Never commit `.env`. It is listed in `.gitignore`.

## How to Run `init.sh`

`init.sh` checks that all required Docker containers are running and healthy.
Run it after `docker compose up -d` to confirm the stack is ready:

```bash
bash init.sh
```

Expected output:
```
=== SHSE init check ===
OK    opensearch
OK    mariadb
OK    redis
OK    nutch
OK    flask
OK    celery_worker
OK    celery_beat
OK    nginx
=======================
All services up.
```

Exit code 0 means all services are healthy. Exit code 1 means at least one service is
down or unhealthy - check `docker compose ps` for details.

## Docker Prerequisites

- **Docker Engine** 24+ - verify with `docker --version`
- **Docker Compose plugin** (v2) - verify with `docker compose version`

The stack uses the `docker compose` (v2) command, not the legacy `docker-compose` binary.
Install Docker Desktop or the standalone Docker Engine + Compose plugin for your OS.
