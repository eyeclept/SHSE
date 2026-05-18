#!/usr/bin/env python3
"""
Author: Richard Baldwin
Date:   2026
Email:  eyeclept@pm.me

Description:
    SHSE command-line interface.
    All commands call the /api/v1/ REST API — no direct database access.
    The web UI and this CLI are two frontends to the same backend; every
    action available in the web UI is available here.

    Credential resolution order (first match wins):
      1. --url / --token CLI flags
      2. SHSE_URL / SHSE_TOKEN environment variables
      3. ~/.config/shse/credentials  (INI, must be mode 0o600)
      4. HashiCorp Vault KV v2       (stub — activated by VAULT_ADDR env var)

    Install (add to PATH or symlink):
        ln -s /path/to/shse/cli/shse.py /usr/local/bin/shse

    Run inside Docker container:
        docker compose exec flask python /app/cli/shse.py <args>

    Connection flags (--url, --token, --no-verify) are subcommand-level options
    and must appear AFTER the subcommand(s), not before.  Use the credentials
    file or SHSE_URL / SHSE_TOKEN environment variables for persistent config.

    Usage:
        shse --help
        shse config setup
        shse config test --url http://localhost:5000 --token shse_...
        shse targets list
        shse targets add --nickname "Wiki.js" --target-url http://host:3000 --port 3000
        shse jobs list --status running
        shse search "linux kernel"
        shse tokens generate "mcp-server"
"""
# Imports
import argparse
import configparser
import getpass
import json
import logging
import os
import ssl
import stat
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

# Globals
_VERSION          = "1.0.0"
_CREDENTIALS_PATH = os.path.expanduser("~/.config/shse/credentials")
_CREDENTIALS_SECTION = "shse"
_VAULT_KV_PATH    = "secret/data/shse/credentials"

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("shse")


# ── Vault integration (stub) ─────────────────────────────────────────────────

def _vault_authenticate(vault_addr: str) -> str:
    """
    Input:  vault_addr — base URL of the Vault server
    Output: Vault client token string
    Details:
        NOT YET IMPLEMENTED.
        Authenticates to HashiCorp Vault and returns a short-lived client token.
        Auth method priority:
          1. VAULT_TOKEN env var (direct token, simplest for scripts)
          2. Vault Agent auto-auth (VAULT_AGENT_ADDR env var)
          3. AppRole via VAULT_ROLE_ID + VAULT_SECRET_ID env vars
        Vault agent is the recommended production method — it handles token
        renewal automatically without exposing credentials in environment variables.
    """
    raise NotImplementedError(
        "Vault authentication is not yet implemented.\n"
        f"  Server: {vault_addr}\n"
        "  Implement VAULT_TOKEN / Vault Agent / AppRole auth in "
        "cli/shse.py:_vault_authenticate()."
    )


def _vault_kv_get(vault_addr: str, vault_token: str, path: str) -> dict:
    """
    Input:  vault_addr  — base URL of the Vault server
            vault_token — Vault client token from _vault_authenticate()
            path        — KV v2 path (e.g. "secret/data/shse/credentials")
    Output: dict of key/value pairs at that path
    Details:
        NOT YET IMPLEMENTED.
        Reads a KV v2 secret from Vault via GET /v1/<path>.
        Vault setup required:
            vault kv put secret/shse/credentials url=https://... token=shse_...
    """
    raise NotImplementedError(
        f"Vault KV read is not yet implemented for path {path}.\n"
        "  Implement GET request to "
        f"{vault_addr}/v1/{path} in cli/shse.py:_vault_kv_get()."
    )


def _load_from_vault(vault_addr: str) -> tuple:
    """
    Input:  vault_addr — base URL of the Vault server (from VAULT_ADDR env var)
    Output: (url, token) tuple loaded from Vault KV v2
    Details:
        NOT YET IMPLEMENTED.
        Orchestrates _vault_authenticate() → _vault_kv_get() to retrieve SHSE
        server URL and API token from HashiCorp Vault.
        Activated automatically when VAULT_ADDR environment variable is set.
    """
    vault_token = _vault_authenticate(vault_addr)
    creds = _vault_kv_get(vault_addr, vault_token, _VAULT_KV_PATH)
    url   = creds.get("url")
    token = creds.get("token")
    if not url or not token:
        raise RuntimeError(
            f"Vault KV at {_VAULT_KV_PATH} is missing 'url' or 'token' field."
        )
    return url, token


# ── Credential loading ────────────────────────────────────────────────────────

def _check_file_permissions(path: str) -> None:
    """
    Input:  path — absolute path to a credentials file
    Output: None; exits with error if permissions are unsafe
    Details:
        Refuses to use a credentials file that is readable by group or other.
        Enterprise requirement: credentials must be accessible only by the
        owning user (mode 0o600 or stricter).
        Prints actionable fix command before exiting.
    """
    try:
        file_stat = os.stat(path)
    except OSError:
        return
    mode = stat.S_IMODE(file_stat.st_mode)
    if mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH):
        _err(
            f"Credentials file has unsafe permissions ({oct(mode)}).\n"
            f"  Fix: chmod 600 {path}\n"
            "  Refusing to use credentials with world/group-readable permissions."
        )
        sys.exit(1)


def _load_from_file() -> tuple:
    """
    Input:  None (reads _CREDENTIALS_PATH)
    Output: (url, token) tuple or (None, None) if file does not exist
    Details:
        Parses ~/.config/shse/credentials as an INI file.
        Verifies file permissions before reading (must be 0o600 or stricter).
    """
    if not os.path.exists(_CREDENTIALS_PATH):
        return None, None
    _check_file_permissions(_CREDENTIALS_PATH)
    cfg = configparser.ConfigParser()
    cfg.read(_CREDENTIALS_PATH)
    if _CREDENTIALS_SECTION not in cfg:
        return None, None
    section = cfg[_CREDENTIALS_SECTION]
    return section.get("url"), section.get("token")


def _load_credentials(args) -> tuple:
    """
    Input:  args — parsed argparse namespace (may have .url and .token attrs)
    Output: (url, token) tuple; exits with error if credentials are unavailable
    Details:
        Resolution order:
          1. CLI flags --url / --token
          2. SHSE_URL / SHSE_TOKEN environment variables
          3. ~/.config/shse/credentials file
          4. HashiCorp Vault (when VAULT_ADDR is set — currently a stub)
    """
    url   = getattr(args, "url",   None) or os.environ.get("SHSE_URL")
    token = getattr(args, "token", None) or os.environ.get("SHSE_TOKEN")
    if url and token:
        return url, token

    vault_addr = os.environ.get("VAULT_ADDR")
    if vault_addr:
        try:
            return _load_from_vault(vault_addr)
        except NotImplementedError as exc:
            _err(str(exc))
            sys.exit(1)
        except Exception as exc:
            _err(f"Vault credential load failed: {exc}")
            sys.exit(1)

    file_url, file_token = _load_from_file()
    if file_url and file_token:
        url   = url   or file_url
        token = token or file_token
        return url, token

    _err(
        "No credentials found.\n"
        "  Run:  shse config setup\n"
        "  Or set SHSE_URL and SHSE_TOKEN environment variables."
    )
    sys.exit(1)


def _write_credentials(url: str, token: str) -> None:
    """
    Input:  url   — SHSE server base URL
            token — raw API token (shse_...)
    Output: None; writes ~/.config/shse/credentials with mode 0o600
    Details:
        Creates the parent directory if needed.  Writes the file then
        immediately sets permissions to 0o600, ensuring the token is
        never visible to other users even briefly.
    """
    cred_dir = os.path.dirname(_CREDENTIALS_PATH)
    os.makedirs(cred_dir, mode=0o700, exist_ok=True)
    cfg = configparser.ConfigParser()
    cfg[_CREDENTIALS_SECTION] = {"url": url, "token": token}
    with open(_CREDENTIALS_PATH, "w") as f:
        cfg.write(f)
    os.chmod(_CREDENTIALS_PATH, 0o600)


# ── HTTP client ───────────────────────────────────────────────────────────────

class _ApiError(Exception):
    """
    Input:  status — HTTP status code; message — error string from response body
    Output: Exception carrying status code and message
    Details: Raised by Client on non-2xx responses so callers can branch by code.
    """
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status  = status
        self.message = message


class Client:
    """
    Input:  url       — SHSE server base URL (e.g. https://shse.example.com)
            token     — raw API token (shse_...)
            verify_tls — False to skip certificate verification (homelab use)
    Output: HTTP client for /api/v1/ endpoints
    Details:
        All requests include Authorization: Bearer <token>.
        Uses stdlib urllib — no third-party dependencies required.
        TLS verification is on by default; disabling it prints a warning.
    """

    def __init__(self, url: str, token: str, verify_tls: bool = True):
        self._base = url.rstrip("/")
        self._token = token
        if verify_tls:
            self._ssl = ssl.create_default_context()
        else:
            _warn("TLS verification disabled — connections are not authenticated.")
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode    = ssl.CERT_NONE
            self._ssl = ctx

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        """
        Input:  method — HTTP verb; path — API path (e.g. /targets);
                body   — optional JSON-serialisable dict for POST/DELETE
        Output: parsed JSON response dict
        Details:
            Raises _ApiError on non-2xx responses.
            Raises ConnectionError when the server is unreachable.
        """
        url  = f"{self._base}/api/v1{path}"
        data = json.dumps(body).encode() if body is not None else None
        req  = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type":  "application/json",
                "Accept":        "application/json",
                "User-Agent":    f"shse-cli/{_VERSION}",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, context=self._ssl, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read())
                msg = payload.get("error", str(exc))
            except Exception:
                msg = str(exc)
            raise _ApiError(exc.code, msg) from exc
        except urllib.error.URLError as exc:
            raise ConnectionError(f"Cannot reach {self._base}: {exc.reason}") from exc

    def get(self, path: str, params: Optional[dict] = None) -> dict:
        """
        Input:  path — API path; params — optional query parameters dict
        Output: parsed JSON response dict
        """
        if params:
            path = path + "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            )
        return self._request("GET", path)

    def post(self, path: str, body: Optional[dict] = None) -> dict:
        """
        Input:  path — API path; body — optional request body dict
        Output: parsed JSON response dict
        """
        return self._request("POST", path, body)

    def delete(self, path: str) -> dict:
        """
        Input:  path — API path
        Output: parsed JSON response dict
        """
        return self._request("DELETE", path)


# ── Output helpers ────────────────────────────────────────────────────────────

def _err(msg: str) -> None:
    """Print an error message to stderr."""
    print(f"error: {msg}", file=sys.stderr)


def _warn(msg: str) -> None:
    """Print a warning message to stderr."""
    print(f"warning: {msg}", file=sys.stderr)


def _table(rows: list, headers: list) -> None:
    """
    Input:  rows    — list of lists (one per row)
            headers — list of column header strings
    Output: None; prints an aligned table to stdout
    Details:
        Computes column widths from headers and data.
        No third-party dependencies (no tabulate).
    """
    all_rows = [headers] + [[str(c) for c in r] for r in rows]
    widths   = [max(len(r[i]) for r in all_rows) for i in range(len(headers))]
    sep      = "  ".join("-" * w for w in widths)
    for i, row in enumerate(all_rows):
        print("  ".join(str(cell).ljust(widths[j]) for j, cell in enumerate(row)))
        if i == 0:
            print(sep)


def _print_token_once(raw: str, name: str) -> None:
    """
    Input:  raw  — raw API token string (shse_...)
            name — token name/label
    Output: None; prints the token prominently with a security warning
    Details:
        Formatted to make clear the token is shown only once.
        Enterprise requirement: single-display tokens must be visually distinct
        so operators do not overlook the store-now requirement.
    """
    border = "=" * (len(raw) + 4)
    print(f"\nGenerated API token: {name}")
    print(f"\n  {border}")
    print(f"  | {raw} |")
    print(f"  {border}")
    print("\n  WARNING: This token will not be shown again. Store it securely.")
    print("  Run:  shse config setup  to save it as your default credentials.\n")


# ── Command handlers ──────────────────────────────────────────────────────────

def cmd_config_setup(args) -> None:
    """
    Input:  args — argparse namespace
    Output: None; writes ~/.config/shse/credentials
    Details:
        Prompts for server URL and API token, tests the connection, then
        writes credentials with mode 0o600.  Does not echo the token during
        input (uses getpass) to prevent shoulder-surfing in shared terminals.
    """
    print("SHSE configuration setup")
    print("─" * 40)
    url = input("Server URL (e.g. https://shse.example.com): ").strip().rstrip("/")
    if not url:
        _err("Server URL cannot be empty.")
        sys.exit(1)
    token = getpass.getpass("API token (shse_...): ").strip()
    if not token.startswith("shse_"):
        _warn("Token does not start with 'shse_' — this may not be a valid SHSE token.")

    print("\nTesting connection...", end=" ", flush=True)
    client = Client(url, token, verify_tls=not getattr(args, "no_verify", False))
    try:
        resp = client.get("/me")
        print("OK")
        print(f"  Authenticated as: {resp.get('username')} (role: {resp.get('role')})")
    except _ApiError as exc:
        print("FAILED")
        _err(f"Server returned {exc.status}: {exc.message}")
        sys.exit(1)
    except ConnectionError as exc:
        print("FAILED")
        _err(str(exc))
        sys.exit(1)

    _write_credentials(url, token)
    print(f"\nCredentials saved to {_CREDENTIALS_PATH} (mode 0o600)")


def cmd_config_test(args) -> None:
    """
    Input:  args — argparse namespace
    Output: None; prints connection status and authenticated user info
    Details:
        Calls GET /api/v1/me to verify credentials and display role.
    """
    url, token = _load_credentials(args)
    client = Client(url, token, verify_tls=not getattr(args, "no_verify", False))
    try:
        resp = client.get("/me")
        print(f"  Server:   {url}")
        print(f"  User:     {resp.get('username')} (id={resp.get('id')})")
        print(f"  Role:     {resp.get('role')}")
        print("  Status:   OK")
    except _ApiError as exc:
        _err(f"Auth check failed ({exc.status}): {exc.message}")
        sys.exit(1)
    except ConnectionError as exc:
        _err(str(exc))
        sys.exit(1)


def cmd_targets_list(args) -> None:
    """
    Input:  args — argparse namespace
    Output: None; prints target table to stdout
    """
    url, token = _load_credentials(args)
    client = Client(url, token, verify_tls=not args.no_verify)
    try:
        targets = client.get("/targets")
    except _ApiError as exc:
        _err(f"{exc.status}: {exc.message}")
        sys.exit(1)
    except ConnectionError as exc:
        _err(str(exc))
        sys.exit(1)
    if not targets:
        print("No targets configured.")
        return
    _table(
        [[t["id"], t.get("nickname") or "—", t.get("url") or "",
          t.get("target_type", ""), t.get("port") or "—", t.get("crawl_depth", 2)]
         for t in targets],
        ["ID", "NICKNAME", "URL", "TYPE", "PORT", "DEPTH"],
    )


def cmd_targets_add(args) -> None:
    """
    Input:  args — argparse namespace with nickname, target_url, type, port, depth
    Output: None; prints new target ID on success
    Details:
        POST /api/v1/targets with the supplied fields.
    """
    url, token = _load_credentials(args)
    client = Client(url, token, verify_tls=not args.no_verify)
    body = {
        "target_type": args.type,
        "nickname":    args.nickname,
        "url":         args.target_url,
        "port":        args.port,
        "crawl_depth": args.depth,
    }
    try:
        resp = client.post("/targets", body)
        print(f"Target added (id={resp['id']})")
    except _ApiError as exc:
        _err(f"{exc.status}: {exc.message}")
        sys.exit(1)
    except ConnectionError as exc:
        _err(str(exc))
        sys.exit(1)


def cmd_targets_delete(args) -> None:
    """
    Input:  args — argparse namespace with id
    Output: None; confirms deletion
    """
    url, token = _load_credentials(args)
    client = Client(url, token, verify_tls=not args.no_verify)
    try:
        client.delete(f"/targets/{args.id}")
        print(f"Target {args.id} deleted.")
    except _ApiError as exc:
        _err(f"{exc.status}: {exc.message}")
        sys.exit(1)
    except ConnectionError as exc:
        _err(str(exc))
        sys.exit(1)


def cmd_targets_crawl(args) -> None:
    """
    Input:  args — argparse namespace with id
    Output: None; prints dispatched task ID
    """
    url, token = _load_credentials(args)
    client = Client(url, token, verify_tls=not args.no_verify)
    try:
        resp = client.post(f"/targets/{args.id}/crawl")
        task_id = resp.get("task_id") or "queued"
        print(f"Crawl dispatched for target {args.id} (task_id={task_id})")
    except _ApiError as exc:
        _err(f"{exc.status}: {exc.message}")
        sys.exit(1)
    except ConnectionError as exc:
        _err(str(exc))
        sys.exit(1)


def cmd_jobs_list(args) -> None:
    """
    Input:  args — argparse namespace; optional .status filter
    Output: None; prints job table to stdout
    """
    url, token = _load_credentials(args)
    client = Client(url, token, verify_tls=not args.no_verify)
    params = {}
    if args.status:
        params["status"] = args.status
    try:
        jobs = client.get("/jobs", params)
    except _ApiError as exc:
        _err(f"{exc.status}: {exc.message}")
        sys.exit(1)
    except ConnectionError as exc:
        _err(str(exc))
        sys.exit(1)
    if not jobs:
        print("No jobs found.")
        return
    _table(
        [[j["id"], j.get("kind", "crawl"), j.get("status", ""),
          j.get("progress", 0), (j.get("started_at") or "—")[:16],
          j.get("message") or ""]
         for j in jobs],
        ["ID", "KIND", "STATUS", "PROGRESS%", "STARTED", "MESSAGE"],
    )


def cmd_jobs_status(args) -> None:
    """
    Input:  args — argparse namespace with id
    Output: None; prints job fields key: value
    """
    url, token = _load_credentials(args)
    client = Client(url, token, verify_tls=not args.no_verify)
    try:
        j = client.get(f"/jobs/{args.id}")
    except _ApiError as exc:
        _err(f"{exc.status}: {exc.message}")
        sys.exit(1)
    except ConnectionError as exc:
        _err(str(exc))
        sys.exit(1)
    for key in ("id", "kind", "status", "progress", "started_at", "finished_at", "message"):
        val = j.get(key)
        if val is not None:
            print(f"  {key:<14}: {val}")


def cmd_search(args) -> None:
    """
    Input:  args — argparse namespace with query, page, limit
    Output: None; prints search results to stdout
    Details:
        Calls GET /api/v1/search.  No authentication required (consistent
        with the web UI search page which is publicly accessible).
    """
    url, token = _load_credentials(args)
    client = Client(url, token, verify_tls=not args.no_verify)
    q = " ".join(args.query)
    try:
        resp = client.get("/search", {"q": q, "page": args.page, "limit": args.limit})
    except _ApiError as exc:
        _err(f"{exc.status}: {exc.message}")
        sys.exit(1)
    except ConnectionError as exc:
        _err(str(exc))
        sys.exit(1)

    total   = resp.get("total", 0)
    took_ms = resp.get("took_ms", 0)
    hits    = resp.get("hits", [])
    print(f"\nQuery: {q!r}  |  {total} result(s)  |  {took_ms}ms\n")
    for i, h in enumerate(hits, 1):
        title   = h.get("title") or h.get("url", "")
        service = h.get("service", "")
        url_str = h.get("url", "")
        snippet = textwrap.shorten(h.get("snippet", ""), width=100, placeholder="…")
        print(f"{i}. {title}")
        if service:
            print(f"   [{service}]  {url_str}")
        else:
            print(f"   {url_str}")
        if snippet:
            print(f"   {snippet}")
        print()
    if not hits:
        print("No results.")


def cmd_tokens_list(args) -> None:
    """
    Input:  args — argparse namespace
    Output: None; prints token table (own tokens; admin sees all)
    """
    url, token = _load_credentials(args)
    client = Client(url, token, verify_tls=not args.no_verify)
    try:
        tokens = client.get("/tokens")
    except _ApiError as exc:
        _err(f"{exc.status}: {exc.message}")
        sys.exit(1)
    except ConnectionError as exc:
        _err(str(exc))
        sys.exit(1)
    if not tokens:
        print("No tokens.")
        return
    _table(
        [[t["id"], t.get("name", ""), t.get("user_id", ""),
          (t.get("created_at") or "—")[:10],
          (t.get("last_used_at") or "never")[:16],
          "active" if t.get("active") else "inactive"]
         for t in tokens],
        ["ID", "NAME", "USER_ID", "CREATED", "LAST_USED", "STATUS"],
    )


def cmd_tokens_generate(args) -> None:
    """
    Input:  args — argparse namespace with name
    Output: None; prints raw token once with security warning
    Details:
        POST /api/v1/tokens.  The raw token appears only in this response
        and cannot be retrieved again.  Prints with a prominent warning.
    """
    url, token = _load_credentials(args)
    client = Client(url, token, verify_tls=not args.no_verify)
    try:
        resp = client.post("/tokens", {"name": args.name})
    except _ApiError as exc:
        _err(f"{exc.status}: {exc.message}")
        sys.exit(1)
    except ConnectionError as exc:
        _err(str(exc))
        sys.exit(1)
    _print_token_once(resp["token"], args.name)


def cmd_tokens_revoke(args) -> None:
    """
    Input:  args — argparse namespace with id
    Output: None; confirms revocation
    Details:
        DELETE /api/v1/tokens/<id>.  Revocation is immediate and permanent.
    """
    url, token = _load_credentials(args)
    client = Client(url, token, verify_tls=not args.no_verify)
    try:
        client.delete(f"/tokens/{args.id}")
        print(f"Token {args.id} revoked.")
    except _ApiError as exc:
        _err(f"{exc.status}: {exc.message}")
        sys.exit(1)
    except ConnectionError as exc:
        _err(str(exc))
        sys.exit(1)


# ── Argument parser ───────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    """
    Input:  None
    Output: Fully configured argparse.ArgumentParser
    Details:
        Constructs the top-level parser and all subcommand parsers.
        Every subcommand inherits --url, --token, and --no-verify from the
        top-level parser via parents=[global_parser].
    """
    global_parser = argparse.ArgumentParser(add_help=False)
    global_parser.add_argument(
        "--url",
        metavar="URL",
        help="SHSE server URL (overrides credentials file and SHSE_URL env var)",
    )
    global_parser.add_argument(
        "--token",
        metavar="TOKEN",
        help="API token (overrides credentials file and SHSE_TOKEN env var)",
    )
    global_parser.add_argument(
        "--no-verify",
        dest="no_verify",
        action="store_true",
        help="Disable TLS certificate verification (use for self-signed certs only)",
    )

    parser = argparse.ArgumentParser(
        prog="shse",
        description="SHSE Search Engine CLI — interact with the search engine via the REST API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              shse config setup
              shse targets list
              shse targets add --nickname "Wiki.js" --target-url http://host:3000 --port 3000
              shse targets crawl 1
              shse jobs list --status running
              shse search "linux kernel"
              shse tokens generate "mcp-server"
              shse tokens revoke 3
        """),
    )
    parser.add_argument("--version", action="version", version=f"shse {_VERSION}")

    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # ── config ────────────────────────────────────────────────────────────────
    p_config = sub.add_parser("config", help="Manage local credentials",
                               parents=[global_parser])
    p_config_sub = p_config.add_subparsers(dest="config_action", metavar="<action>")
    p_config_sub.required = True
    p_config_sub.add_parser("setup", help="Interactive credentials setup",
                             parents=[global_parser])
    p_config_sub.add_parser("test",  help="Verify connection and credentials",
                             parents=[global_parser])

    # ── targets ───────────────────────────────────────────────────────────────
    p_targets = sub.add_parser("targets", help="Manage crawl targets",
                                parents=[global_parser])
    p_targets_sub = p_targets.add_subparsers(dest="targets_action", metavar="<action>")
    p_targets_sub.required = True

    p_targets_sub.add_parser("list", help="List all crawl targets",
                              parents=[global_parser])

    p_add = p_targets_sub.add_parser("add", help="Add a crawl target",
                                     parents=[global_parser])
    p_add.add_argument("--nickname", required=True, metavar="NAME",
                       help="Human-readable name for the target")
    p_add.add_argument("--target-url", required=True, dest="target_url", metavar="URL",
                       help="Seed URL for the crawler")
    p_add.add_argument("--type", default="service", dest="type",
                       choices=["service", "network", "oai-pmh", "feed", "api-push"],
                       help="Target type (default: service)")
    p_add.add_argument("--port",  type=int, metavar="PORT",
                       help="Target port (e.g. 80, 3000)")
    p_add.add_argument("--depth", type=int, default=2, metavar="N",
                       help="Crawl depth (default: 2)")

    p_del = p_targets_sub.add_parser("delete", help="Delete a crawl target",
                                     parents=[global_parser])
    p_del.add_argument("id", type=int, metavar="TARGET_ID")

    p_crawl = p_targets_sub.add_parser("crawl", help="Trigger a crawl job",
                                       parents=[global_parser])
    p_crawl.add_argument("id", type=int, metavar="TARGET_ID")

    # ── jobs ──────────────────────────────────────────────────────────────────
    p_jobs = sub.add_parser("jobs", help="View crawl job status",
                             parents=[global_parser])
    p_jobs_sub = p_jobs.add_subparsers(dest="jobs_action", metavar="<action>")
    p_jobs_sub.required = True

    p_jlist = p_jobs_sub.add_parser("list", help="List recent jobs",
                                    parents=[global_parser])
    p_jlist.add_argument("--status",
                         choices=["queued", "started", "running", "success", "done",
                                  "failure", "failed"],
                         help="Filter by status")

    p_jstatus = p_jobs_sub.add_parser("status", help="Get a single job's status",
                                      parents=[global_parser])
    p_jstatus.add_argument("id", type=int, metavar="JOB_ID")

    # ── search ────────────────────────────────────────────────────────────────
    p_search = sub.add_parser("search", help="Search the index",
                               parents=[global_parser])
    p_search.add_argument("query", nargs="+", metavar="TERM",
                          help="Search query (space-separated terms are joined)")
    p_search.add_argument("--page",  type=int, default=1,  metavar="N")
    p_search.add_argument("--limit", type=int, default=10, metavar="N",
                          help="Results per page (max 50, default 10)")

    # ── tokens ────────────────────────────────────────────────────────────────
    p_tokens = sub.add_parser("tokens", help="Manage API tokens",
                               parents=[global_parser])
    p_tokens_sub = p_tokens.add_subparsers(dest="tokens_action", metavar="<action>")
    p_tokens_sub.required = True

    p_tokens_sub.add_parser("list", help="List your API tokens (admin sees all)",
                             parents=[global_parser])

    p_gen = p_tokens_sub.add_parser("generate", help="Generate a new API token",
                                    parents=[global_parser])
    p_gen.add_argument("name", metavar="NAME",
                       help="Label for the token (e.g. 'mcp-server', 'ci-pipeline')")

    p_rev = p_tokens_sub.add_parser("revoke", help="Revoke a token (immediate)",
                                    parents=[global_parser])
    p_rev.add_argument("id", type=int, metavar="TOKEN_ID")

    return parser


# ── Dispatch ──────────────────────────────────────────────────────────────────

_DISPATCH = {
    ("config",  "setup"):  cmd_config_setup,
    ("config",  "test"):   cmd_config_test,
    ("targets", "list"):   cmd_targets_list,
    ("targets", "add"):    cmd_targets_add,
    ("targets", "delete"): cmd_targets_delete,
    ("targets", "crawl"):  cmd_targets_crawl,
    ("jobs",    "list"):   cmd_jobs_list,
    ("jobs",    "status"): cmd_jobs_status,
    ("search",  None):     cmd_search,
    ("tokens",  "list"):   cmd_tokens_list,
    ("tokens",  "generate"): cmd_tokens_generate,
    ("tokens",  "revoke"): cmd_tokens_revoke,
}


def main() -> None:
    """
    Input:  sys.argv
    Output: None; dispatches to the appropriate command handler
    Details:
        Entry point.  Resolves the (command, sub-action) key and calls the
        matching handler.  Unhandled exceptions are caught at the top level;
        a clean error message is printed and the process exits with code 1.
    """
    parser = _build_parser()
    args   = parser.parse_args()

    sub_action = (
        getattr(args, "config_action",  None)
        or getattr(args, "targets_action", None)
        or getattr(args, "jobs_action",    None)
        or getattr(args, "tokens_action",  None)
    )
    key = (args.command, sub_action)

    handler = _DISPATCH.get(key)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    try:
        handler(args)
    except KeyboardInterrupt:
        print()
        sys.exit(130)
    except Exception as exc:
        _err(f"unexpected error: {exc}")
        logger.debug("traceback", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
