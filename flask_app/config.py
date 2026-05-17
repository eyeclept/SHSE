"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Flask configuration.
    Non-secret values are read from config.ini (checked into git).
    Secrets (passwords, keys, tokens) are read from environment variables only.
    Docker services may override any config.ini value via their environment: blocks.
"""
# Imports
import configparser
import os

# Globals
_cfg = configparser.ConfigParser()
_cfg.read(os.path.join(os.path.dirname(__file__), "..", "config.ini"))


def _c(section, key, fallback=""):
    """
    Input:  section, key — config.ini location; fallback — used when absent
    Output: str — env var (if set) > config.ini value > fallback
    Details:
        Env var name is derived as SECTION_KEY (uppercase, hyphens → underscores).
        Docker services use this convention to override specific keys per-container
        (e.g. MARIADB_HOST=mariadb inside the compose network).
    """
    env_key = f"{section.upper()}_{key.upper().replace('-', '_')}"
    if env_key in os.environ:
        return os.environ[env_key]
    try:
        return _cfg[section][key]
    except KeyError:
        return fallback


# Functions
class Config:
    """
    Input: config.ini and environment variables
    Output: Configuration object consumed by Flask and Celery
    Details:
        Secrets are read exclusively from environment variables.
        All other settings come from config.ini with env var override.
    """

    # ── Secrets (env only — never in config.ini) ───────────────────────────
    SECRET_KEY             = os.environ.get("SECRET_KEY", "change-me")
    MARIADB_PASSWORD       = os.environ.get("MARIADB_PASSWORD", "")
    OPENSEARCH_PASSWORD    = os.environ.get("OPENSEARCH_INITIAL_ADMIN_PASSWORD", "")
    REDIS_PASSWORD         = os.environ.get("REDIS_PASSWORD", "")
    SSO_CLIENT_SECRET      = os.environ.get("SSO_CLIENT_SECRET", "")
    SMTP_PASSWORD          = os.environ.get("SMTP_PASSWORD", "")

    # ── MariaDB ────────────────────────────────────────────────────────────
    MARIADB_HOST = _c("mariadb", "host", "localhost")
    MARIADB_PORT = _c("mariadb", "port", "3306")
    MARIADB_DB   = _c("mariadb", "db",   "shse")
    MARIADB_USER = _c("mariadb", "user", "shse_user")
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{MARIADB_USER}:{MARIADB_PASSWORD}"
        f"@{MARIADB_HOST}:{MARIADB_PORT}/{MARIADB_DB}"
    )

    # ── OpenSearch ─────────────────────────────────────────────────────────
    OPENSEARCH_HOST = _c("opensearch", "host", "localhost")
    OPENSEARCH_PORT = int(_c("opensearch", "port", "9200"))
    OPENSEARCH_USER = _c("opensearch", "user", "admin")

    # ── Redis / Celery ─────────────────────────────────────────────────────
    REDIS_HOST = _c("redis", "host", "localhost")
    REDIS_PORT = int(_c("redis", "port", "6379"))
    CELERY_BROKER_URL = (
        f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/0"
        if REDIS_PASSWORD else
        f"redis://{REDIS_HOST}:{REDIS_PORT}/0"
    )

    # ── Nutch ──────────────────────────────────────────────────────────────
    NUTCH_HOST = _c("nutch", "host", "localhost")
    NUTCH_PORT = int(_c("nutch", "port", "8081"))

    # ── LLM API ────────────────────────────────────────────────────────────
    LLM_API_BASE       = _c("llm", "api_base",       "http://localhost:11434/v1")
    LLM_EMBED_MODEL    = _c("llm", "embed_model",    "nomic-embed-text")
    LLM_GEN_MODEL      = _c("llm", "gen_model",      "granite4.1:8b")
    LLM_REWRITE_MODEL  = _c("llm", "rewrite_model",  "granite4.1:3b")
    LLM_TRANSLATE_MODEL= _c("llm", "translate_model","aya-expanse:8b")
    QUERY_REWRITE_ENABLED = _c("llm", "query_rewrite", "false").lower() in ("true", "1")
    CPU_EMBED_FALLBACK    = _c("llm", "cpu_fallback",  "false").lower() in ("true", "1")

    # ── StarDict ───────────────────────────────────────────────────────────
    STARDICT_DICT_PATH = _c("stardict", "dict_path", "/app/dicts")

    # ── TLS ────────────────────────────────────────────────────────────────
    INTERNAL_TLS_VERIFY = _c("tls", "internal_verify", "true").lower() == "true"

    # ── SSO (disabled by default; local password auth is the default) ──────
    SSO_ENABLED      = _c("sso", "enabled",      "false").lower() == "true"
    SSO_PROVIDER_URL = _c("sso", "provider_url", "")
    SSO_CLIENT_ID    = _c("sso", "client_id",    "")
    SSO_ADMIN_GROUP  = _c("sso", "admin_group",  "admin")
    AUTH_LOCAL_ENABLED = _c("sso", "local_auth", "true").lower() == "true"

    # ── WebAuthn (FIDO2 / YubiKey) ─────────────────────────────────────────
    WEBAUTHN_RP_ID   = _c("webauthn", "rp_id",   "localhost")
    WEBAUTHN_RP_NAME = _c("webauthn", "rp_name", "SHSE")
    WEBAUTHN_ORIGIN  = _c("webauthn", "origin",  "http://localhost:5000")

    # ── SMTP (disabled when host is blank) ─────────────────────────────────
    SMTP_HOST = _c("smtp", "host", "")
    SMTP_PORT = int(_c("smtp", "port", "587"))
    SMTP_USER = _c("smtp", "user", "")
    SMTP_FROM = _c("smtp", "from", "noreply@example.com")
    SMTP_TLS  = _c("smtp", "tls",  "true").lower() == "true"
    APP_URL   = _c("app",  "url",  "http://localhost:5000")

    # ── MCP Server ─────────────────────────────────────────────────────────
    MCP_HOST     = _c("mcp", "host",     "0.0.0.0")
    MCP_PORT     = int(_c("mcp", "port",     "8765"))
    MCP_RESULT_K = int(_c("mcp", "result_k", "10"))


if __name__ == "__main__":
    pass
