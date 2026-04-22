# Nutch Integration

## Nutch Version

The project uses `apache/nutch:latest`, which contains Nutch **1.23-SNAPSHOT** built from source at `/root/nutch_source`.

The REST server binary is:

```
/root/nutch_source/runtime/local/bin/nutch startserver
```

By default the server listens on `localhost:8081`. To expose it to other containers, pass `-host 0.0.0.0`:

```
/root/nutch_source/runtime/local/bin/nutch startserver -host 0.0.0.0 -port 8081
```

> **Note:** The container currently runs `tail -f /dev/null` (keeps the container alive without starting the HTTP server). The REST server must be started explicitly via `docker exec nutch ...` or by changing the `command` in `docker-compose.yml`. This is intentional for the current dev phase; Epic 9 Celery tasks will start crawls via this server.

---

## REST API Reference

Base URL: `http://nutch:8081` (from other Docker Compose services) or `http://localhost:8081` (from host).

All endpoints accept and return `application/json`.

### Admin — `/admin`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/` | Server status and metadata |
| GET | `/admin/stop` | Gracefully stop the Nutch server |

### Config — `/config`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/config/` | List all configuration IDs |
| GET | `/config/{configId}` | Get all properties for a config |
| GET | `/config/{configId}/{propertyId}` | Get a single property value |
| DELETE | `/config/{configId}` | Delete a configuration |
| POST | `/config/create` | Create a new configuration |
| PUT | `/config/{configId}/{propertyId}` | Update a single property |

### Job — `/job`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/job/?crawlId=` | List all jobs for a crawl |
| GET | `/job/{id}?crawlId=` | Get job info |
| GET | `/job/{id}/stop?crawlId=` | Stop a running job |
| GET | `/job/{id}/abort?crawlId=` | Abort a job immediately |
| POST | `/job/create` | Submit a new job |

**POST `/job/create` request body:**

```json
{
  "crawlId": "crawl-001",
  "type": "FETCH",
  "confId": "default",
  "args": {
    "threads": 10
  }
}
```

**`type` values** (from `JobManager.JobType` enum):
`INJECT`, `GENERATE`, `FETCH`, `PARSE`, `UPDATEDB`, `INDEX`, `READDB`, `CLASS`, `INVERTLINKS`, `DEDUP`

**`JobInfo` response fields:**

```json
{
  "id": "...",
  "crawlId": "crawl-001",
  "type": "FETCH",
  "confId": "default",
  "args": {},
  "result": {},
  "state": "RUNNING",
  "msg": ""
}
```

**`state` values:** `IDLE`, `RUNNING`, `FINISHED`, `FAILED`, `KILLED`, `STOPPING`, `KILLING`

### Seed — `/seed`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/seed/` | List all seed lists |
| POST | `/seed/create` | Create a seed file (list of URLs) |

### DB — `/db`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/db/crawldb` | Query the crawl DB |
| GET | `/db/fetchdb?from=0&to=0` | Fetch DB entries (paginated) |

### Services — `/services`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/services/commoncrawldump/{crawlId}` | List dump paths for a crawl |
| POST | `/services/commoncrawldump` | Export a Common Crawl dump |

---

## Crawl Trigger Flow

A minimal crawl sequence using the REST API:

1. **Create seed** — `POST /seed/create` with a list of seed URLs; Nutch returns a seed path.
2. **Inject** — `POST /job/create` with `type: INJECT` and `args.seedDir` pointing to the seed path.
3. **Generate** — `POST /job/create` with `type: GENERATE`.
4. **Fetch** — `POST /job/create` with `type: FETCH`.
5. **Parse** — `POST /job/create` with `type: PARSE`.
6. **Update DB** — `POST /job/create` with `type: UPDATEDB`.
7. **Poll** — `GET /job/{id}?crawlId=` until `state == FINISHED` or `state == FAILED`.
8. **Read results** — `POST /db/crawldb` to query indexed content.

Each job must finish before the next step is started. `flask_app/services/nutch.py` wraps this sequence in `trigger_crawl()` and `fetch_results()`.

---

## TLS Patch Usage

Nutch performs outbound HTTP/HTTPS requests to crawl targets. For targets with self-signed certificates, hostname verification must be disabled at the Nutch configuration level.

The `nutch/nutch-site.xml` file in this repo is the override configuration template. To disable TLS verification for a crawl:

1. Set `http.tls.certificates.insecure` to `true` in `nutch-site.xml` (or pass it as a config property via `PUT /config/{configId}/{propertyId}`).
2. Mount the updated `nutch-site.xml` into the container at `/root/nutch_source/runtime/local/conf/nutch-site.xml`.

This is applied per-crawl by Epic 6 Step 4 (`flask_app/services/nutch.py` sets the property via the config API before triggering the crawl when `tls_verify=false` is set on a target).

> **Security:** Only disable TLS verification for specific internal targets. The `tls_verify` field on `crawler_targets` rows controls this per-target. A global override (`INTERNAL_TLS_VERIFY=false` env var) is handled in Epic 13.
