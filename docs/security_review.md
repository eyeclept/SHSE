# SHSE — Security Review

**Date:** 2026-05-16  
**Scope:** flask_app/, docker-compose.yml, nginx/, requirements.txt  
**Methodology:** Manual code review (Steps 1–3, 5–8); pip-audit dependency scan (Step 4)

---

## Executive Summary

| Severity | Count |
|----------|-------|
| High     | 9     |
| Medium   | 7     |
| Low      | 4     |
| **Total**| **20**|

**High findings that must be remediated before exposing SHSE to untrusted networks:**

- SEC-001: No login rate limiting — brute-force attacks unrestricted
- SEC-003: No CSRF protection on any POST route
- SEC-008: Redis exposed on 0.0.0.0:6379 with no authentication
- SEC-011: Login success and failure not logged (no audit trail for auth events)
- SEC-017a: authlib 1.3.0 — 8 CVEs including critical JWT forgery (CVE-2026-27962)
- SEC-017b: pymysql 1.1.0 — SQL injection via untrusted JSON keys (CVE-2024-36039)

All High findings carry remediation guidance below. Medium findings should be scheduled for the next sprint. Low findings are noted for awareness.

---

## Findings Table

| ID | Category | Severity | Description | Status |
|----|----------|----------|-------------|--------|
| SEC-001 | Auth Hardening | High | No login rate limiting or account lockout | Open |
| SEC-002 | Auth Hardening | Medium | Session cookie Secure and SameSite flags not set | Open |
| SEC-003 | Auth Hardening | High | No CSRF protection on any POST route | Open |
| SEC-004 | Auth Hardening | Low | No PERMANENT_SESSION_LIFETIME; sessions do not expire | Open |
| SEC-005 | Auth Hardening | Medium | Registration and setup routes accept any-length passwords | Open |
| SEC-006 | Secrets | Medium | SECRET_KEY defaults to "change-me" if env var unset | Open |
| SEC-007 | XSS | Low | snippet_html rendered with \| safe; relies on server-side text extraction | Open |
| SEC-008 | Container/Network | High | Redis exposed on 0.0.0.0:6379 with no auth; MariaDB on 0.0.0.0:3306 | Open |
| SEC-009 | Container/Network | Medium | Nginx TLS config lacks ssl_protocols directive; may allow TLS 1.0/1.1 | Open |
| SEC-010 | Access Control | Low | Several routes use manual is_authenticated check instead of @login_required | Open |
| SEC-011 | Audit Trail | High | Login success and failure not logged (username, IP) | Open |
| SEC-012 | Audit Trail | High | Failed login IP not recorded; no brute-force signal in logs | Open |
| SEC-013 | Audit Trail | Low | Admin role promote/demote events not logged | Open |
| SEC-014 | Audit Trail | Low | Crawl target add/remove/trigger not logged | Open |
| SEC-015 | SSRF | Low | Crawl subsystem fetches admin-set URLs; admin trust is appropriate but undocumented | Open |
| SEC-016 | Auth Hardening | Medium | Default admin/admin account auto-seeded on boot in __init__.py | Open |
| SEC-017a | Dependencies | High | authlib 1.3.0: 8 CVEs (JWT forgery, padding oracle, CSRF, DoS) | Open |
| SEC-017b | Dependencies | High | pymysql 1.1.0: CVE-2024-36039 — SQL injection via JSON keys | Open |
| SEC-017c | Dependencies | Medium | werkzeug 3.0.1: 5 CVEs (resource exhaustion, debugger RCE on dev machines) | Open |
| SEC-017d | Dependencies | Medium | requests 2.31.0: 3 CVEs (verify=False session sticky, netrc leak, temp file) | Open |

---

## Step-by-Step Findings

### Step 1 — Authentication Hardening

**Files reviewed:** `flask_app/routes/auth.py`, `flask_app/models/user.py`, `flask_app/config.py`, `flask_app/__init__.py`

| Check | Result |
|-------|--------|
| Login rate limiting or lockout | ✗ **SEC-001 — HIGH** |
| Session cookie HttpOnly | ✓ Flask default is HttpOnly=True |
| Session cookie Secure | ✗ **SEC-002 — MEDIUM** — not explicitly set |
| Session cookie SameSite=Lax | ✗ **SEC-002 — MEDIUM** — not configured |
| CSRF protection on POST routes | ✗ **SEC-003 — HIGH** |
| Session expiry (PERMANENT_SESSION_LIFETIME) | ✗ **SEC-004 — LOW** |
| Password minimum length on registration | ✗ **SEC-005 — MEDIUM** |
| bcrypt work factor | ✓ gensalt() default = 12 rounds |
| Plaintext passwords in logs | ✓ None found |
| SECRET_KEY non-default | ✗ **SEC-006 — MEDIUM** (defaults to "change-me") |
| Default admin account seeded | ✗ **SEC-016 — MEDIUM** (admin/admin auto-created in __init__.py) |

**Notes:**
- `settings_password` enforces an 8-character minimum but `register` and `setup` routes do not.
- The app detects `admin/admin` on login and flashes a warning — this is a partial mitigation for SEC-016.

---

### Step 2 — Input Validation and Injection

**Files reviewed:** All route and service files

| Check | Result |
|-------|--------|
| SQL injection — ORM/parameterized queries | ✓ SQLAlchemy ORM used throughout; no raw SQL string interpolation |
| XSS — Jinja2 auto-escaping | ✓ Enabled by default for all .html templates |
| XSS — unsafe \| safe filter usage | ✗ **SEC-007 — LOW** (see below) |
| Command injection — subprocess with user input | ✓ No subprocess calls; nutch.py uses requests library |
| Path traversal — file upload paths | ✓ No user-specified file paths; YAML upload parsed in memory |

**SEC-007 detail:** `flask_app/templates/_result_item.html:39` renders `{{ r.snippet_html | safe }}`. The `snippet_html` value is built from OpenSearch highlight fragments of crawled content. Indexed text is HTML-stripped by `_TextExtractor` before storage, which mitigates the risk in the normal crawl path. However, content ingested via API push adapters or OAI-PMH is not guaranteed to pass through the same text extractor. The template comment acknowledges this: "Never pass raw user input through {{ r.snippet_html | safe }} — the server-side highlighter must escape first then inject the tags." An explicit `markupsafe.escape()` call on the fragment before injecting `<strong>` tags is recommended.

---

### Step 3 — Secrets Management

| Check | Result |
|-------|--------|
| Hardcoded credentials in flask_app/*.py | ✓ None found (grep confirmed) |
| .env in .gitignore | ✓ Confirmed |
| .env in git history | ✓ Not present (git log --all --full-history -- .env returned no commits) |
| SECRET_KEY set from env | ✗ **SEC-006** — defaults to "change-me" |
| .env.example uses placeholders | ✓ Confirmed from prior sessions |
| SSO_CLIENT_SECRET read from env | ✓ No hardcoded value |

---

### Step 4 — Dependency Vulnerability Scan

**Tool:** pip-audit 2.x  
**Command:** `pip-audit --requirement requirements.txt --format=json`  
**Result:** 21 vulnerabilities across 7 packages

#### High Findings (CVSS estimated ≥ 7.0)

| Package | Version | CVE | Fix | Description |
|---------|---------|-----|-----|-------------|
| authlib | 1.3.0 | CVE-2026-27962 | 1.6.9 | JWK Header Injection — attacker can forge arbitrary JWT tokens that pass verification |
| authlib | 1.3.0 | CVE-2026-28490 | 1.6.9 | Cryptographic padding oracle vulnerability in JWE |
| authlib | 1.3.0 | PYSEC-2024-52 | 1.3.1 | Algorithm confusion with asymmetric public keys |
| authlib | 1.3.0 | CVE-2025-59420 | 1.6.4 | JWS accepts tokens declaring unknown critical header parameters |
| authlib | 1.3.0 | CVE-2025-68158 | 1.6.6 | CSRF — OAuth state stored in cache allows session fixation |
| authlib | 1.3.0 | CVE-2025-61920 | 1.6.5 | Unbounded JWS/JWT header and signature segments (DoS) |
| authlib | 1.3.0 | CVE-2025-62706 | 1.6.5 | JWE zip=DEF unbounded DEFLATE decompression (bomb) |
| authlib | 1.3.0 | CVE-2026-41425 | 1.6.11 | CSRF protection missing on cache feature in OAuth integrations |
| pymysql | 1.1.0 | CVE-2024-36039 | 1.1.1 | SQL injection if used with untrusted JSON input (key names not escaped) |
| werkzeug | 3.0.1 | CVE-2024-34069 | 3.0.3 | Debugger allows remote code execution (only affects DEBUG=True deployments) |

#### Medium Findings (CVSS estimated 4.0–6.9)

| Package | Version | CVE | Fix | Description |
|---------|---------|-----|-----|-------------|
| werkzeug | 3.0.1 | CVE-2024-49767 | 3.0.6 | multipart/form-data resource exhaustion |
| werkzeug | 3.0.1 | CVE-2024-49766 | 3.0.6 | safe_join() Windows UNC path traversal (Linux: not affected) |
| werkzeug | 3.0.1 | CVE-2025-66221 | 3.1.4 | Windows device names in safe_join (Linux: not affected) |
| werkzeug | 3.0.1 | CVE-2026-21860 | 3.1.5 | Windows device names with extensions (Linux: not affected) |
| werkzeug | 3.0.1 | CVE-2026-27199 | 3.1.6 | Windows device names with path segments (Linux: not affected) |
| requests | 2.31.0 | CVE-2024-35195 | 2.32.0 | verify=False becomes sticky for a Session after first use |
| requests | 2.31.0 | CVE-2024-47081 | 2.32.4 | URL parsing issue leaks .netrc credentials |
| requests | 2.31.0 | CVE-2026-25645 | 2.33.0 | Predictable temp filenames in extract_zipped_paths() |
| flask | 3.0.0 | CVE-2026-27205 | 3.1.3 | Vary: Cookie header not set for some session access patterns |
| python-dotenv | 1.0.0 | CVE-2026-28684 | 1.2.2 | set_key/unset_key follow symlinks when rewriting .env files |

#### Low Findings

| Package | Version | CVE | Fix | Description |
|---------|---------|-----|-----|-------------|
| pytest | 7.4.3 | CVE-2025-71176 | 9.0.3 | Predictable /tmp/pytest-of-{user} path (test runner only) |

**Remediation for authlib (HIGH — SEC-017a):** Upgrade to `authlib>=1.6.11`. This is the most critical dependency finding. The JWT forgery vulnerability (CVE-2026-27962) could allow an attacker to bypass SSO authentication entirely when `SSO_ENABLED=true`. Even when SSO is disabled, the padding oracle and algorithm confusion CVEs represent significant cryptographic weaknesses.

**Remediation for pymysql (HIGH — SEC-017b):** Upgrade to `pymysql>=1.1.1`. The SQL injection risk only applies if JSON data with untrusted keys is passed directly to PyMySQL. SHSE uses SQLAlchemy ORM for all DB access, which parameterizes queries. The risk is low in practice but the package should still be upgraded.

---

### Step 5 — Container and Network Security

**Files reviewed:** `docker-compose.yml`, `nginx/nginx.conf`

| Check | Result |
|-------|--------|
| Containers running as root unnecessarily | ✓ init containers use root only for chown; main services do not specify root |
| privileged: true or cap_add: SYS_ADMIN | ✓ Not present |
| Ports bound to 0.0.0.0 that should be localhost-only | ✗ **SEC-008 — HIGH** |
| Sensitive host paths in bind mounts | ✓ Only ./data/, ./dicts/, ./nginx/ mounted |
| Nginx TLS 1.2+ only | ✗ **SEC-009 — MEDIUM** |

**SEC-008 detail — Port exposure:**

| Service | Port | Risk |
|---------|------|------|
| opensearch | 9200 | Admin-password protected but exposed to network — Medium |
| mariadb | 3306 | Exposed to network; should be 127.0.0.1:3306 — Medium |
| **redis** | **6379** | **No auth; exposed to network — HIGH** |
| nutch | 8081 | REST API with no auth; exposed to network — Medium |
| flask | 5000 | Direct access bypasses Nginx security controls — Low |

Redis has no password configured. Any host on the same network segment can connect to Redis and: (a) read/write session data, (b) inject malicious Celery tasks, (c) corrupt the search cache. To fix: add `command: redis-server --requirepass ${REDIS_PASSWORD}` to the redis service and bind `127.0.0.1:6379:6379`.

**SEC-009 detail:** `nginx/nginx.conf` does not include a `ssl_protocols` directive. Nginx's default allows TLS 1.0 and TLS 1.1 depending on the linked OpenSSL version. Add `ssl_protocols TLSv1.2 TLSv1.3;` and `ssl_ciphers HIGH:!aNULL:!MD5;` to the HTTPS server block.

---

### Step 6 — Access Control and Privilege Escalation

| Check | Result |
|-------|--------|
| All data-modifying routes require auth | ✓ All routes check authentication (via decorator or manual check) |
| Admin routes check current_user.role == "admin" | ✓ @admin_required enforces this on all admin_bp routes |
| Self-demote guard on /admin/users/<id>/demote | ✓ Blocks self-demotion |
| /api/* endpoints enforce auth where required | ✓ /api/admin-check checks admin role; search endpoints intentionally public |
| Nginx auth_request for /admin/ | ✓ Configured and uses /api/admin-check which validates session |

**SEC-010 detail:** Several `search_bp` routes (`settings_password`, `history`, `history/clear`, `settings`, `totp_setup`, `totp_disable`, `webauthn_register`, `webauthn_remove`) use `if not current_user.is_authenticated: return redirect(...)` rather than the `@login_required` decorator. Both approaches are functionally equivalent but the decorator is more explicit and less likely to be accidentally omitted during code review. This is a Low finding (no practical bypass exists).

---

### Step 7 — Audit Trail Completeness

| Event | Logged | Severity |
|-------|--------|----------|
| Successful login (username, IP) | ✗ **SEC-011 — HIGH** | Missing |
| Failed login attempts (username, IP) | ✗ **SEC-012 — HIGH** | Missing |
| Password change (username) | ✓ logged at INFO | — |
| Password reset token issued | ✓ logged at INFO | — |
| Admin role changes (actor, target, action) | ✗ **SEC-013 — LOW** | Missing |
| Crawl target add/remove/trigger | ✗ **SEC-014 — LOW** | Missing |
| 2FA enroll (TOTP) | ✓ logged at INFO | — |
| 2FA disable (TOTP) | ✓ logged at INFO | — |
| WebAuthn key register | ✓ logged at INFO | — |
| WebAuthn key remove | ✓ logged at INFO | — |
| Failed TOTP code | ✓ logged at WARNING | — |
| Plaintext passwords/tokens in logs | ✓ None found | — |

**SEC-011/SEC-012 detail:** The `login()` route calls `login_user(user)` on success and returns a 401 on failure, but neither branch logs. Add:
- Success: `logger.info("login: user_id=%s username=%s ip=%s", user.id, user.username, request.remote_addr)`
- Failure: `logger.warning("login: failed attempt for username=%s ip=%s", username, request.remote_addr)`

---

### Step 8 — OWASP Top 10 2021 Checklist

| Category | Status | Finding IDs |
|----------|--------|-------------|
| A01 Broken Access Control | ⚠ Minor Finding | SEC-010 (Low) |
| A02 Cryptographic Failures | ⚠ Findings | SEC-006, SEC-009, SEC-017a |
| A03 Injection | ⚠ Low Finding | SEC-007 (Low XSS risk) |
| A04 Insecure Design | ✗ High Findings | SEC-001, SEC-003, SEC-016 |
| A05 Security Misconfiguration | ✗ High Findings | SEC-002, SEC-006, SEC-008, SEC-009 |
| A06 Vulnerable and Outdated Components | ✗ High Findings | SEC-017a, SEC-017b, SEC-017c, SEC-017d |
| A07 Identification and Authentication Failures | ✗ High Findings | SEC-001, SEC-003, SEC-004, SEC-005 |
| A08 Software and Data Integrity Failures | ⚠ Via SEC-017a | SEC-017a (authlib JWT forgery) |
| A09 Security Logging and Monitoring Failures | ✗ High Findings | SEC-011, SEC-012 |
| A10 SSRF | ⚠ Low Finding | SEC-015 |

**A10 SSRF detail (SEC-015):** The crawl subsystem (`_discover_urls`, `_fetch_page_text`) fetches arbitrary URLs stored in `crawler_targets.url`. These URLs are set by admin users only. Admin trust is the authorization gate, and there are no localhost restrictions. This is acceptable for a homelab context but should be documented: if SHSE is operated with multiple admin users or the admin account is compromised, the crawl subsystem becomes an SSRF vector. Consider adding a URL allowlist or block for loopback/link-local addresses.

---

## Remediation Guidance for High Findings

### SEC-001 — No Login Rate Limiting

**Risk:** Unlimited password guessing. A 4-character PIN would fall in under 10,000 requests.

**Fix:** Add Flask-Limiter:
```python
# requirements.txt: flask-limiter>=3.5
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(get_remote_address, app=app, default_limits=["200/day"])

@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10/minute")
def login(): ...
```

---

### SEC-003 — No CSRF Protection

**Risk:** Any authenticated user who visits a malicious page can have state-changing requests (password change, target delete, role change) executed on their behalf.

**Fix:** Add Flask-WTF:
```python
# requirements.txt: flask-wtf>=1.2
from flask_wtf.csrf import CSRFProtect
csrf = CSRFProtect()
csrf.init_app(app)
```
Add `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` to all forms.

---

### SEC-008 — Redis Exposed Without Authentication

**Risk:** Any host on the same network can read session data, inject Celery tasks, or corrupt the cache. This is a critical risk on multi-tenant networks.

**Fix in docker-compose.yml:**
```yaml
redis:
  command: redis-server --requirepass ${REDIS_PASSWORD}
  ports:
    - "127.0.0.1:6379:6379"  # bind to localhost only
```
Set `REDIS_URL` environment variable to include the password where Redis is used.

Also bind MariaDB to localhost:
```yaml
ports:
  - "127.0.0.1:3306:3306"
```

---

### SEC-011/SEC-012 — Login Events Not Logged

**Risk:** No way to detect brute-force attacks, account compromises, or unauthorized access after the fact.

**Fix in `flask_app/routes/auth.py` login():**
```python
if user and user.check_password(password):
    logger.info("login: success user_id=%s username=%s ip=%s",
                user.id, user.username, request.remote_addr)
    # ... existing 2FA routing
else:
    logger.warning("login: failed username=%s ip=%s",
                   username, request.remote_addr)
    return render_template(...), 401
```

---

### SEC-017a — authlib Vulnerabilities

**Risk:** CVE-2026-27962 allows an unauthenticated attacker to forge arbitrary JWT tokens that pass signature verification when `SSO_ENABLED=true`. An attacker with knowledge of the OIDC flow can authenticate as any user including admins without valid credentials.

**Fix:** Upgrade `authlib` to `>=1.6.11` in `requirements.txt`. This is the single highest-priority dependency upgrade.

```
authlib>=1.6.11
```

---

### SEC-017b — pymysql SQL Injection

**Risk:** CVE-2024-36039 — PyMySQL allows SQL injection if JSON data with untrusted keys is used in queries. SHSE uses SQLAlchemy ORM which parameterizes all queries, so the practical risk is low. Upgrade as a precaution.

**Fix:** Upgrade `pymysql` to `>=1.1.1`.

---

## Recommended Upgrade Targets

| Package | Current | Minimum Fix | Notes |
|---------|---------|-------------|-------|
| authlib | 1.3.0 | 1.6.11 | **Critical — upgrade first** |
| pymysql | 1.1.0 | 1.1.1 | Low practical risk; upgrade for hygiene |
| werkzeug | 3.0.1 | 3.1.6 | Windows CVEs irrelevant on Linux; upgrade for CVE-2024-49767 |
| requests | 2.31.0 | 2.33.0 | Upgrade for netrc and temp file CVEs |
| flask | 3.0.0 | 3.1.3 | Upgrade for Vary:Cookie fix |
| python-dotenv | 1.0.0 | 1.2.2 | Low risk; upgrade for symlink fix |
| pytest | 7.4.3 | 9.0.3 | Dev dependency; upgrade separately |

---

*All High findings either require remediation or an explicit accepted-risk note before SHSE is deployed on a network with untrusted access.*
