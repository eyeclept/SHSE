# SHSE - Nginx

Nginx sits in front of Flask as a TLS termination and reverse proxy layer.
It also enforces a second layer of admin access control via `auth_request`.

---

## Proxy Configuration

`nginx/nginx.conf` contains two server blocks:

**Port 80** - redirects all HTTP traffic to HTTPS:
```nginx
server {
    listen 80;
    return 301 https://$host$request_uri;
}
```

**Port 443** - TLS termination and reverse proxy to Flask:
```nginx
server {
    listen 443 ssl;
    ssl_certificate     /etc/nginx/certs/cert.pem;
    ssl_certificate_key /etc/nginx/certs/key.pem;
    ...
    location / {
        proxy_pass http://flask:5000;
    }
}
```

Host ports (from `docker-compose.yml`): HTTP → `8888`, HTTPS → `8443`.

---

## SSL Certificate Setup

A self-signed certificate is pre-generated at `nginx/certs/cert.pem` and
`nginx/certs/key.pem` for development. Both files are in `.gitignore`.

To replace with a real certificate (e.g. from step-ca or Let's Encrypt):

1. Copy `cert.pem` and `key.pem` into `nginx/certs/`
2. Restart Nginx: `docker compose restart nginx`

The Nginx service will refuse to start if either file is missing.

---

## `/admin/*` Restriction

Nginx enforces admin access via the `auth_request` directive - a sub-request
to `GET /api/admin-check` is issued before proxying any `/admin/` request.

```nginx
location = /api/admin-check {
    internal;
    proxy_pass              http://flask:5000/api/admin-check;
    proxy_pass_request_body off;
    proxy_set_header        Content-Length "";
    proxy_set_header        Cookie $http_cookie;
}

location /admin {
    auth_request /api/admin-check;
    error_page 403 = @admin_forbidden;
    proxy_pass http://flask:5000;
    ...
}
```

Flask's `GET /api/admin-check` endpoint returns:
- **200** - authenticated admin
- **403** - authenticated non-admin or unauthenticated

When Nginx receives 403 from the sub-request, it returns 403 to the client
without proxying to Flask at all. This is defence-in-depth: Flask also enforces
`@admin_required` on every admin route.

---

## How to Replace the Certificate

```bash
# Generate a new self-signed cert (dev only):
openssl req -x509 -newkey rsa:4096 -keyout nginx/certs/key.pem \
    -out nginx/certs/cert.pem -days 365 -nodes \
    -subj "/CN=shse.homelab.lan"

# Reload Nginx:
docker compose restart nginx
```

For production, mount certs issued by your internal CA (step-ca, Vault PKI):
```yaml
# In docker-compose.yml nginx service volumes:
volumes:
  - /etc/step/certs/shse.crt:/etc/nginx/certs/cert.pem:ro
  - /etc/step/certs/shse.key:/etc/nginx/certs/key.pem:ro
```
