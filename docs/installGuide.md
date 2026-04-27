# SHSE — Installation Guide

This guide walks through installing SHSE from scratch on a Linux host with Docker.

---

## Prerequisites

| Requirement | Minimum version | Check |
|---|---|---|
| Docker Engine | 24.0 | `docker --version` |
| Docker Compose plugin | v2.0 | `docker compose version` |
| Git | any | `git --version` |
| Disk space | 10 GB free | for images + OpenSearch data |
| RAM | 4 GB free | OpenSearch needs at least 2 GB |

---

## Step 1 — Clone the repository

```bash
git clone https://github.com/youruser/shse.git
cd shse
```

---

## Step 2 — Create the environment file

```bash
cp .env.example .env
```

Open `.env` and fill in all required values:

```ini
# Flask
SECRET_KEY=change-me-to-a-long-random-string

# MariaDB
MARIADB_DATABASE=shse
MARIADB_USER=shse
MARIADB_PASSWORD=your-db-password
MARIADB_ROOT_PASSWORD=your-root-password

# OpenSearch
OPENSEARCH_INITIAL_ADMIN_PASSWORD=Min8Chars1Special!

# Redis (no changes required for local Docker)
REDIS_HOST=redis
REDIS_PORT=6379
```

Rules for `OPENSEARCH_INITIAL_ADMIN_PASSWORD`: minimum 8 characters, at least one uppercase letter, one number, and one special character.

---

## Step 3 — (Optional) Configure the LLM API

Skip this step if you do not have a local LLM API. SHSE works without one; AI summaries and semantic search will be disabled but all other features are available.

```ini
# OpenAI-compatible endpoint (Ollama, LiteLLM, vLLM, etc.)
LLM_API_BASE=http://192.168.1.50:11434/v1
LLM_EMBED_MODEL=nomic-embed-text
LLM_GEN_MODEL=llama3
```

If your LLM API runs on the host machine (not inside Docker), use:

```ini
LLM_API_BASE=http://host.docker.internal:11434/v1
```

---

## Step 4 — (Optional) Configure SSO

Skip this step to use local username/password auth.

```ini
SSO_ENABLED=true
SSO_CLIENT_ID=shse
SSO_CLIENT_SECRET=your-client-secret
SSO_DISCOVERY_URL=https://auth.homelab.lan/application/o/shse/.well-known/openid-configuration
SSO_ADMIN_GROUP=shse-admins   # OIDC groups claim value that grants admin role
```

---

## Step 5 — Start the stack

```bash
docker compose up -d
```

On first boot, Docker pulls all images (OpenSearch, MariaDB, Redis, Nginx, Nutch). This may take several minutes depending on your connection.

Check that all containers are running:

```bash
docker compose ps
```

All services should show `healthy` or `running`. OpenSearch takes the longest to become healthy (30–60 seconds).

---

## Step 6 — Verify the stack

```bash
bash init.sh
```

This runs a quick check confirming all services are reachable. If any service fails, check its logs:

```bash
docker compose logs <service-name> --tail=50
```

---

## Step 7 — Apply database migrations

Migrations run automatically inside the Flask container on startup. Confirm they applied:

```bash
docker exec flask python -c "
from flask_app import create_app, db
import sqlalchemy as sa
app = create_app()
with app.app_context():
    with db.engine.connect() as conn:
        rows = conn.execute(sa.text('SHOW TABLES')).fetchall()
        for r in rows: print(r[0])
"
```

Expected output includes: `users`, `search_history`, `crawler_targets`, `crawl_jobs`, `alembic_version`.

---

## Step 8 — Create the admin account

Navigate to `https://localhost:8443/setup` (or `http://localhost:8888/setup` for plain HTTP).

This page only appears when no admin account exists. Enter a username and password and click Create.

---

## Step 9 — Create the OpenSearch index

```bash
python cli.py create-index
```

This is idempotent — safe to run multiple times.

---

## Step 10 — (Optional) Enable auto-start on boot

A systemd service file is included. To install it:

```bash
sudo cp systemd/shse.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable shse
sudo systemctl start shse
```

Check status:

```bash
systemctl status shse
journalctl -u shse -f
```

See [docs/systemd.md](systemd.md) for details.

---

## Upgrading

To pull the latest code and rebuild:

```bash
git pull
docker compose build
docker compose up -d
```

Migrations apply automatically on container start.

---

## Ports

| Port | Service | Protocol |
|---|---|---|
| 8888 | Nginx (HTTP → HTTPS redirect) | HTTP |
| 8443 | Nginx (main UI + API) | HTTPS |
| 8081 | Nutch REST API (optional direct access) | HTTP |
| 9200 | OpenSearch (optional direct access) | HTTPS |

All ports are on `localhost` by default. To expose on a network interface, edit the `ports:` entries in `docker-compose.yml`.

---

## SSL Certificate

SHSE ships with a self-signed certificate for local development. To replace it with a real cert:

```bash
cp your-cert.pem nginx/certs/cert.pem
cp your-key.pem  nginx/certs/key.pem
docker compose restart nginx
```

See [docs/nginx.md](nginx.md) for details.

---

## Uninstalling

```bash
docker compose down -v    # stops containers and deletes named volumes (ALL DATA)
```

To keep data volumes, omit `-v`.
