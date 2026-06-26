"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Shared building blocks for the admin blueprint package. Holds the cross-cutting
    pieces that more than one concern module needs: the ``admin_required`` access
    decorator (used by every route) and the service-health probe/cache
    (``_check_services``/``_probe_services``), which is called from both health.py
    (dashboard, /_health, index ops) and targets.py (targets list, edit). Lifting
    these here avoids sibling imports between concern modules.
"""
# Imports
import logging
import time
from functools import wraps

import requests as _requests
from flask import abort, redirect, url_for
from flask_login import current_user
from sqlalchemy import text

# Globals
logger = logging.getLogger(__name__)

_PROBE_TIMEOUT = 3   # seconds per health probe
_HEALTH_TTL = 5      # seconds; a short-TTL snapshot collapses the 5s /_health
                     # poll and the list/edit page badges into one sweep/window


# Functions
def admin_required(f):
    """
    Input: view function
    Output: decorated view function
    Details:
        Redirects unauthenticated users to login.
        Returns 403 for authenticated non-admin users.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if current_user.role != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated


def _check_services():
    """
    Input: None
    Output: dict {service: {status, latency_ms, message}}
    Details:
        Returns a short-TTL cached snapshot of _probe_services(). The dashboard,
        the 5s /_health HTMX poll, and the targets/index list and edit pages all
        call this, so caching means one real sweep per _HEALTH_TTL window instead
        of a full probe per page load. Bypassed under Flask TESTING.
    """
    from flask_app.services.cache import cached_json
    return cached_json("shse:health", _HEALTH_TTL, _probe_services)


def _probe_services():
    """
    Input: None
    Output: dict {service: {status, latency_ms, message}}
    Details:
        Probes OpenSearch, Nutch, LLM API, Redis, and MariaDB with short
        timeouts. Returns 'up', 'down', or 'degraded' per service.
        All exceptions are caught so a single unreachable service never
        prevents the dashboard from rendering.
    """
    from concurrent.futures import ThreadPoolExecutor
    from flask_app.services.opensearch import get_client as os_client
    from flask_app.config import Config
    from flask_app import db

    # Each probe is independent and self-contained: it catches its own
    # exceptions and returns a (key, result) tuple, so it is safe to run
    # concurrently. The six network probes below are dispatched to a thread
    # pool; the MariaDB probe stays on the request thread because db.session is
    # request/thread-scoped and must not be touched from a pool worker. Running
    # them concurrently bounds the total wait at roughly one _PROBE_TIMEOUT
    # instead of the sum of all probe timeouts.

    def _probe_opensearch():
        try:
            t0 = time.monotonic()
            client = os_client()
            health = client.cluster.health()
            ms = int((time.monotonic() - t0) * 1000)
            status_map = {"green": "up", "yellow": "degraded", "red": "down"}
            os_status = status_map.get(health.get("status", "red"), "down")
            num_nodes = health.get("number_of_nodes", 1)
            unassigned = health.get("unassigned_shards", 0)
            relocating = health.get("relocating_shards", 0)
            detail = None
            if os_status == "degraded":
                parts = []
                if unassigned:
                    note = " — replica shards cannot be placed on a single-node cluster (harmless)" if num_nodes == 1 else ""
                    parts.append(f"{unassigned} unassigned shard(s){note}")
                if relocating:
                    parts.append(f"{relocating} relocating shard(s)")
                detail = "; ".join(parts) if parts else "cluster status yellow"
            elif os_status == "down":
                detail = f"cluster status red — {unassigned} unassigned shard(s)"
            return ("opensearch", {"status": os_status, "latency_ms": ms, "message": detail})
        except Exception as exc:
            logger.warning("OpenSearch probe failed", exc_info=True)
            return ("opensearch", {"status": "down", "latency_ms": None, "message": str(exc)[:80]})

    def _probe_nutch():
        try:
            t0 = time.monotonic()
            resp = _requests.get(
                f"http://{Config.NUTCH_HOST}:{Config.NUTCH_PORT}/admin/",
                timeout=_PROBE_TIMEOUT,
            )
            ms = int((time.monotonic() - t0) * 1000)
            return ("nutch", {
                "status": "up" if resp.ok else "degraded",
                "latency_ms": ms,
                "message": None if resp.ok else f"HTTP {resp.status_code}",
            })
        except Exception as exc:
            _exc = str(exc)
            if "Max retries" in _exc or "Connection refused" in _exc:
                logger.warning("Nutch REST server unreachable — reporting disabled", exc_info=True)
                return ("nutch", {"status": "disabled", "latency_ms": None, "message": "REST server not running in this image"})
            logger.warning("Nutch probe failed", exc_info=True)
            return ("nutch", {"status": "down", "latency_ms": None, "message": _exc[:80]})

    def _probe_llm():
        try:
            t0 = time.monotonic()
            llm_base = Config.LLM_API_BASE.rstrip("/")
            resp = _requests.get(f"{llm_base}/models", timeout=_PROBE_TIMEOUT)
            ms = int((time.monotonic() - t0) * 1000)
            return ("llm_api", {
                "status": "up" if resp.ok else "degraded",
                "latency_ms": ms,
                "message": None if resp.ok else f"HTTP {resp.status_code}",
            })
        except Exception as exc:
            logger.warning("LLM API probe failed", exc_info=True)
            return ("llm_api", {"status": "down", "latency_ms": None, "message": str(exc)[:80]})

    def _probe_redis():
        try:
            import redis as _redis
            t0 = time.monotonic()
            r = _redis.Redis(
                host=Config.REDIS_HOST,
                port=Config.REDIS_PORT,
                password=Config.REDIS_PASSWORD or None,
                socket_connect_timeout=_PROBE_TIMEOUT,
            )
            r.ping()
            ms = int((time.monotonic() - t0) * 1000)
            return ("redis", {"status": "up", "latency_ms": ms, "message": None})
        except Exception as exc:
            logger.warning("Redis probe failed", exc_info=True)
            return ("redis", {"status": "down", "latency_ms": None, "message": str(exc)[:80]})

    def _probe_celery():
        try:
            from celery_worker.app import celery as _celery
            t0 = time.monotonic()
            inspector = _celery.control.inspect(timeout=_PROBE_TIMEOUT)
            active = inspector.ping()
            ms = int((time.monotonic() - t0) * 1000)
            if active:
                return ("celery", {"status": "up", "latency_ms": ms, "message": f"{len(active)} worker(s) responding"})
            return ("celery", {"status": "down", "latency_ms": ms, "message": "No workers responded"})
        except Exception as exc:
            logger.warning("Celery probe failed", exc_info=True)
            return ("celery", {"status": "down", "latency_ms": None, "message": str(exc)[:80]})

    def _probe_sso():
        if not Config.SSO_ENABLED:
            return ("sso", {"status": "disabled", "latency_ms": None, "message": "SSO_ENABLED=false"})
        discovery_url = getattr(Config, "SSO_PROVIDER_URL", "").rstrip("/") + "/.well-known/openid-configuration"
        try:
            t0 = time.monotonic()
            resp = _requests.get(discovery_url, timeout=_PROBE_TIMEOUT)
            ms = int((time.monotonic() - t0) * 1000)
            return ("sso", {
                "status": "up" if resp.ok else "degraded",
                "latency_ms": ms,
                "message": None if resp.ok else f"HTTP {resp.status_code}",
            })
        except Exception as exc:
            logger.warning("SSO discovery probe failed", exc_info=True)
            return ("sso", {"status": "down", "latency_ms": None, "message": str(exc)[:80]})

    results = {}

    # MariaDB stays on the request thread (db.session is request-scoped).
    try:
        t0 = time.monotonic()
        db.session.execute(text("SELECT 1"))
        ms = int((time.monotonic() - t0) * 1000)
        results["mariadb"] = {"status": "up", "latency_ms": ms, "message": None}
    except Exception as exc:
        logger.warning("MariaDB probe failed", exc_info=True)
        results["mariadb"] = {"status": "down", "latency_ms": None, "message": str(exc)[:80]}

    # Run the six independent network probes concurrently.
    network_probes = (_probe_opensearch, _probe_nutch, _probe_llm,
                      _probe_redis, _probe_celery, _probe_sso)
    with ThreadPoolExecutor(max_workers=len(network_probes)) as pool:
        for key, value in pool.map(lambda p: p(), network_probes):
            results[key] = value

    # Preserve the original key order for stable dashboard rendering.
    order = ("opensearch", "nutch", "llm_api", "redis", "celery", "mariadb", "sso")
    return {k: results[k] for k in order if k in results}
