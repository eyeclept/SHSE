# SHSE — Database

## Schema

### `users`

| Column | Type | Constraints |
|---|---|---|
| `id` | INT | PRIMARY KEY, AUTO_INCREMENT |
| `username` | VARCHAR(64) | NOT NULL, UNIQUE |
| `password_hash` | VARCHAR(256) | nullable (null for SSO-only accounts) |
| `role` | ENUM('admin','user') | NOT NULL |
| `sso_identity` | VARCHAR(256) | nullable (OIDC subject claim) |

### `search_history`

| Column | Type | Constraints |
|---|---|---|
| `id` | INT | PRIMARY KEY, AUTO_INCREMENT |
| `user_id` | INT | NOT NULL, FK → `users.id` |
| `query` | VARCHAR(512) | NOT NULL |
| `timestamp` | DATETIME | nullable |

### `crawler_targets`

| Column | Type | Constraints |
|---|---|---|
| `id` | INT | PRIMARY KEY, AUTO_INCREMENT |
| `nickname` | VARCHAR(128) | nullable |
| `target_type` | ENUM('service','network','oai-pmh','feed','api-push') | NOT NULL |
| `url` | VARCHAR(512) | nullable |
| `ip` | VARCHAR(64) | nullable |
| `network` | VARCHAR(64) | nullable (CIDR block for network targets) |
| `port` | INT | nullable |
| `route` | VARCHAR(256) | nullable |
| `service` | VARCHAR(32) | nullable |
| `tls_verify` | BOOLEAN | nullable |
| `endpoint` | VARCHAR(256) | nullable (OAI-PMH endpoint path, e.g. `/oai2d`) |
| `feed_path` | VARCHAR(256) | nullable (RSS/Atom feed path, e.g. `/rss`) |
| `adapter` | VARCHAR(256) | nullable (api-push adapter module name) |
| `schedule_yaml` | TEXT | nullable (serialised schedule block) |
| `yaml_source` | TEXT | nullable (full source YAML blob) |

### `crawl_jobs`

| Column | Type | Constraints |
|---|---|---|
| `id` | INT | PRIMARY KEY, AUTO_INCREMENT |
| `task_id` | VARCHAR(256) | UNIQUE, nullable (Celery task UUID) |
| `target_id` | INT | nullable, FK → `crawler_targets.id` |
| `status` | VARCHAR(64) | nullable |
| `started_at` | DATETIME | nullable |
| `finished_at` | DATETIME | nullable |

**`status` values:**

| Value | Meaning |
|---|---|
| `started` | Task is executing |
| `success` | Task completed without error |
| `failure` | Task raised an exception |

`target_id` is set to `NULL` when the referenced `crawler_targets` row is deleted (e.g. when a new YAML config is uploaded via `persist_targets`). Orphaned job rows are preserved for audit purposes.

## Migration Commands

Run all pending migrations (from project root):
```bash
flask db upgrade
```

Roll back the last migration:
```bash
flask db downgrade
```

Show current revision:
```bash
flask db current
```

Show migration history:
```bash
flask db history
```

Inside Docker (Flask container):
```bash
docker exec flask flask db upgrade
```

## Entity-Relationship Diagram

```
users ──────────────────────────── search_history
  id (PK)                            id (PK)
  username                           user_id (FK → users.id)
  password_hash                      query
  role                               timestamp
  sso_identity

crawler_targets ─────────────────── crawl_jobs
  id (PK)                            id (PK)
  nickname                           task_id (UNIQUE)
  target_type                        target_id (FK → crawler_targets.id, nullable)
  url / ip / network / port          status
  route / service / tls_verify       started_at
  endpoint / feed_path / adapter     finished_at
  schedule_yaml / yaml_source
```

## Foreign Key Constraints

| Constraint | Child column | References | On delete |
|---|---|---|---|
| `search_history.user_id` | `search_history.user_id` | `users.id` | RESTRICT |
| `crawl_jobs.target_id` | `crawl_jobs.target_id` | `crawler_targets.id` | SET NULL (via application logic) |

Both FKs are enforced by MariaDB's InnoDB engine. Inserting a child row with a
nonexistent parent ID raises `IntegrityError` (errno 1452). `crawl_jobs.target_id`
is nullable so that job history is preserved when targets are replaced.
