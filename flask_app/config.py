"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Flask configuration. All service endpoints and feature flags are read
    from environment variables with safe defaults.
"""
# Imports
import os

# Globals

# Functions
class Config:
    """
    Input: Environment variables
    Output: Configuration object consumed by Flask
    Details:
        Covers MariaDB, OpenSearch, Redis, Nutch, LLM API, TLS, and SSO settings.
    """
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")

    # MariaDB
    MARIADB_HOST = os.environ.get("MARIADB_HOST", "localhost")
    MARIADB_PORT = os.environ.get("MARIADB_PORT", "3306")
    MARIADB_DB = os.environ.get("MARIADB_DB", "shse")
    MARIADB_USER = os.environ.get("MARIADB_USER", "shse_user")
    MARIADB_PASSWORD = os.environ.get("MARIADB_PASSWORD", "")
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{MARIADB_USER}:{MARIADB_PASSWORD}"
        f"@{MARIADB_HOST}:{MARIADB_PORT}/{MARIADB_DB}"
    )

    # OpenSearch
    OPENSEARCH_HOST = os.environ.get("OPENSEARCH_HOST", "localhost")
    OPENSEARCH_PORT = int(os.environ.get("OPENSEARCH_PORT", 9200))
    OPENSEARCH_USER = os.environ.get("OPENSEARCH_USER", "admin")
    OPENSEARCH_PASSWORD = os.environ.get("OPENSEARCH_INITIAL_ADMIN_PASSWORD", "")

    # Redis / Celery
    REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
    CELERY_BROKER_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"

    # Nutch
    NUTCH_HOST = os.environ.get("NUTCH_HOST", "localhost")
    NUTCH_PORT = int(os.environ.get("NUTCH_PORT", 8080))

    # LLM API (OpenAI-compatible endpoint; in the lab stack this is LiteLLM)
    LLM_API_BASE = os.environ.get("LLM_API_BASE", "http://localhost:11434/v1")
    LLM_EMBED_MODEL = os.environ.get("LLM_EMBED_MODEL", "nomic-embed-text")
    LLM_GEN_MODEL = os.environ.get("LLM_GEN_MODEL", "granite4.1:8b")
    LLM_REWRITE_MODEL = os.environ.get("LLM_REWRITE_MODEL", "granite4.1:3b")
    QUERY_REWRITE_ENABLED = os.environ.get("QUERY_REWRITE_ENABLED", "false").lower() in ("true", "1")

    # TLS
    INTERNAL_TLS_VERIFY = os.environ.get("INTERNAL_TLS_VERIFY", "true").lower() == "true"

    # SSO (disabled by default; local password auth is the default)
    SSO_ENABLED = os.environ.get("SSO_ENABLED", "false").lower() == "true"
    SSO_PROVIDER_URL = os.environ.get("SSO_PROVIDER_URL", "")
    SSO_CLIENT_ID = os.environ.get("SSO_CLIENT_ID", "")
    SSO_CLIENT_SECRET = os.environ.get("SSO_CLIENT_SECRET", "")
    SSO_ADMIN_GROUP = os.environ.get("SSO_ADMIN_GROUP", "admin")
    AUTH_LOCAL_ENABLED = os.environ.get("AUTH_LOCAL_ENABLED", "true").lower() == "true"


if __name__ == "__main__":
    pass
