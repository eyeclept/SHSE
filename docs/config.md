# Crawler Configuration (YAML)

SHSE crawl targets are declared in a YAML file uploaded via the admin UI.
The file has two top-level keys: `defaults` and `targets`.

---

## YAML Format Reference

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
  - type: network
    network: 192.168.1.0/24

  - type: service
    nickname: discourse
    url: discourse.lab.internal
    ip: 10.0.0.51
    port: 443
    tls_verify: false
    schedule:
      frequency: daily
      time: "03:00"
      timezone: UTC

  - type: oai-pmh
    nickname: invenio-rdm
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

---

## `defaults` Block Rules

- Any field in `defaults` is inherited by every target that does not explicitly set it.
- Inheritance is a deep merge: nested blocks (e.g. `schedule`) are merged key-by-key,
  so a target that sets only `schedule.frequency` still inherits `schedule.timezone` etc.
- A target-level value always wins over the corresponding default.

---

## Schedule Syntax

The `schedule` block is supported on all target types.

| Field | Type | Description |
|---|---|---|
| `frequency` | string | `hourly`, `daily`, `weekly`, `monthly` |
| `day` | string or int | Day name (e.g. `sunday`) for weekly; day number (1–31) for monthly |
| `time` | string | `"HH:MM"` (24-hour) — used for daily/weekly/monthly |
| `timezone` | string | IANA timezone name (e.g. `UTC`, `America/New_York`) |

Schedules are converted to Celery Beat `crontab` entries at runtime by
`config_parser.to_beat_entry()`.

---

## Field Reference by Target Type

### `type: service`

Triggers a Nutch crawl against a specific host.

| Field | Required | Description |
|---|---|---|
| `nickname` | yes | Short identifier used as `service_nickname` in OpenSearch |
| `url` | yes | Hostname or IP address |
| `ip` | no | Explicit IP (overrides DNS resolution) |
| `port` | no (default: `80`) | TCP port |
| `route` | no (default: `/`) | Starting path for the crawl |
| `service` | no (default: `http`) | Protocol hint |
| `tls_verify` | no (default: `true`) | Set `false` for self-signed certs |
| `crawl_depth` | no (default: `2`) | BFS link hops to follow from the seed URL; `0` = seed page only, `1` = seed + directly linked pages |
| `schedule` | no | Crawl schedule block |

### `type: network`

Triggers a network scan / broad Nutch sweep of a CIDR subnet.

| Field | Required | Description |
|---|---|---|
| `network` | yes | CIDR notation (e.g. `192.168.1.0/24`) |
| `schedule` | no | Scan schedule block |

### `type: oai-pmh`

Triggers a Metha OAI-PMH harvest.

| Field | Required | Description |
|---|---|---|
| `nickname` | yes | Identifier used as `service_nickname` in OpenSearch |
| `url` | yes | Base URL of the OAI-PMH repository |
| `endpoint` | yes | OAI endpoint path (e.g. `/oai2d`) |
| `schedule` | no | Harvest schedule block |

### `type: feed`

Ingests an RSS/Atom/ActivityPub feed.

| Field | Required | Description |
|---|---|---|
| `nickname` | yes | Identifier used as `service_nickname` in OpenSearch |
| `url` | yes | Base URL of the site |
| `feed_path` | yes | Path to the feed (e.g. `/rss`, `/feed.atom`) |
| `schedule` | no | Ingest schedule block |

### `type: api-push`

Pulls content via a custom adapter script and pushes to OpenSearch.

| Field | Required | Description |
|---|---|---|
| `nickname` | yes | Identifier used as `service_nickname` in OpenSearch |
| `url` | yes | API base URL |
| `adapter` | yes | Adapter module name (e.g. `discourse_adapter`) |
| `schedule` | no | Pull schedule block |
