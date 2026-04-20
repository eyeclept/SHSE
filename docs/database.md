# SHSE — Database

## Schema

### `users`

| Column | Type | Constraints |
|---|---|---|
| `id` | INT | PRIMARY KEY, AUTO_INCREMENT |
| `username` | VARCHAR(64) | NOT NULL, UNIQUE |
| `password_hash` | VARCHAR(256) | nullable (null when SSO-only account) |
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
| `target_type` | ENUM('service','network') | NOT NULL |
| `url` | VARCHAR(512) | nullable |
| `ip` | VARCHAR(64) | nullable |
| `network` | VARCHAR(64) | nullable (CIDR block for network scans) |
| `port` | INT | nullable |
| `route` | VARCHAR(256) | nullable |
| `service` | VARCHAR(32) | nullable |
| `tls_verify` | BOOLEAN | nullable |
| `schedule_yaml` | TEXT | nullable (raw schedule block from YAML) |
| `yaml_source` | TEXT | nullable (full source YAML blob) |

### `crawl_jobs`

| Column | Type | Constraints |
|---|---|---|
| `id` | INT | PRIMARY KEY, AUTO_INCREMENT |
| `task_id` | VARCHAR(256) | UNIQUE, nullable (Celery task UUID) |
| `target_id` | INT | nullable, FK → `crawler_targets.id` |
| `status` | VARCHAR(64) | nullable (`queued`, `running`, `complete`, `failed`) |
| `started_at` | DATETIME | nullable |
| `finished_at` | DATETIME | nullable |

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
  target_type                        target_id (FK → crawler_targets.id)
  url / ip / network / port          status
  route / service / tls_verify       started_at
  schedule_yaml / yaml_source        finished_at
```

## Foreign Key Constraints

| Constraint | Child column | References |
|---|---|---|
| `search_history.user_id` | `search_history.user_id` | `users.id` |
| `crawl_jobs.target_id` | `crawl_jobs.target_id` | `crawler_targets.id` |

Both FKs are enforced at the database level by MariaDB's InnoDB engine.
Attempting to insert a child row with a nonexistent parent ID raises an
`IntegrityError` (errno 1452).
