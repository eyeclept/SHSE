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

> **Note:** The container runs `tail -f /dev/null` to stay alive without auto-starting the HTTP server. Start the REST server before triggering crawls:
> ```bash
> docker exec nutch /root/nutch_source/runtime/local/bin/nutch startserver -host 0.0.0.0 -port 8081
> ```
> `flask_app/services/nutch.py` connects to this server when dispatching crawl tasks.

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

1. The property `http.tls.certificates.check` controls TLS verification in Nutch 1.23. Set it to `false` via the config API before triggering a crawl:
   ```
   PUT /config/default/http.tls.certificates.check
   Body: false   (Content-Type: text/plain)
   ```
2. Alternatively, set the property in `nutch/nutch-site.xml` and mount it into the container at `/root/nutch_source/runtime/local/conf/nutch-site.xml`.

`flask_app/services/nutch.py` applies this override automatically at the start of `trigger_crawl()` when the target has `tls_verify=false`. The override is scoped to the `default` config and persists for the lifetime of the Nutch server process.

> **Security:** Only disable TLS verification for specific internal targets with known self-signed certificates. The `tls_verify` field on `crawler_targets` rows controls this per-target.
