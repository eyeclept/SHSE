# SHSE - TLS / Self-Signed Certificate Handling

SHSE operates on a private network where self-signed certificates are common.
Two layers of TLS control exist: per-target bypass for crawled services, and a
global bypass flag for all internal service calls (OpenSearch, Nutch, LLM API).

---

## Per-target `tls_verify` flag

Set `tls_verify: false` on any crawler target to bypass certificate verification
for that target only:

```yaml
targets:
  - type: service
    nickname: internal-app
    url: app.homelab.lan
    port: 443
    service: https
    tls_verify: false    # bypass for this target only
```

**What it affects:**

1. **Nutch crawl** - before triggering the Nutch pipeline, the crawl task calls
   `PUT /config/default/http.tls.certificates.check` with value `false` on the
   Nutch REST server when `tls_verify=False`.

2. **Page text fetch** - after Nutch returns crawled URLs, `_fetch_page_text(url,
   tls_verify=False)` is called for each URL to retrieve the full HTML. The
   `requests.get()` call passes `verify=False`.

**What it does NOT affect:** other targets in the same crawl run, or any other
service (OpenSearch, LLM API, Redis).

---

## `INTERNAL_TLS_VERIFY` global flag

Set `INTERNAL_TLS_VERIFY=false` in `.env` to disable TLS verification on **all**
internal service calls made by the Flask and Celery processes:

| Service | Effect |
|---|---|
| Nutch REST API | `get_session()` returns a `requests.Session` with `session.verify=False` |
| OpenSearch | `verify_certs=False` is already the default in `get_client()` |
| LLM API | `requests.post()` inside `get_embedding()` / `generate_summary()` always passes `verify=True` - override via `LLM_API_BASE` with a non-TLS URL if needed |

**When to use:** fully trusted LAN environments where all services share an internal
CA that is not in the system trust store. The recommended production approach is to
mount the CA certificate (e.g. from step-ca or Vault PKI) into all containers so
`INTERNAL_TLS_VERIFY` can stay `true`.

---

## TLS Warning Banner

The admin dashboard at `/admin/` shows a warning banner whenever any
`CrawlerTarget` row has `tls_verify=False`. The banner links to `/admin/targets`
so the admin can review which targets have verification disabled.

The banner only appears in the admin UI - regular users do not see it.

---

## Security Implications

| Action | Risk |
|---|---|
| `tls_verify: false` on a single internal target | Low - limited to one service on your LAN |
| `INTERNAL_TLS_VERIFY=false` globally | Medium - all internal API calls skip cert validation |
| `tls_verify: false` for a public internet target | **Do not do this** - SHSE only indexes internal services |

The recommended long-term fix for homelab self-signed certificates is to mount
your internal root CA certificate into the relevant containers:

```bash
# Example: mount step-ca root into the Celery worker container
# In docker-compose.yml celery_worker service:
volumes:
  - /etc/ssl/certs/step-ca-root.crt:/usr/local/share/ca-certificates/homelab-ca.crt:ro

# Then in Dockerfile.celery, run:
# RUN update-ca-certificates
```

Once the CA is trusted at the OS level, all `requests` calls automatically
validate certificates issued by it without any `verify=False` workarounds.
