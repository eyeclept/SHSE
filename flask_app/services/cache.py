"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Process-wide Redis client (lazy singleton) and a small read-through JSON
    cache helper. Used for short-TTL caching of expensive read-mostly
    aggregations such as the index-stats blobs shown on the home, admin, and
    /api/stats pages. Degrades silently to the live producer whenever Redis is
    unavailable, and is bypassed entirely under Flask TESTING so unit tests that
    mock the producer stay deterministic.
"""
# Imports
import json
import logging
import threading

# Globals
logger = logging.getLogger(__name__)

# Short TTL for advisory aggregation blobs: fresh enough for a dashboard, long
# enough to absorb the home page's repeated multi-query OpenSearch sweep.
STATS_TTL = 30

# Lazily-built, process-wide Redis client (db=1). redis.Redis owns a thread-safe
# connection pool, so one instance is reused across every cache operation.
_redis_client = None
_redis_lock = threading.Lock()


# Functions
def get_redis():
    """
    Input: None
    Output: redis.Redis client (db=1)
    Details:
        Returns a process-wide singleton, built on first use from Config.
        Thread-safe via double-checked locking.
    """
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    with _redis_lock:
        if _redis_client is None:
            import redis
            from flask_app.config import Config
            _redis_client = redis.Redis(
                host=Config.REDIS_HOST,
                port=Config.REDIS_PORT,
                password=Config.REDIS_PASSWORD or None,
                db=1,
            )
    return _redis_client


def cached_json(key, ttl, producer):
    """
    Input:
        key      - str, Redis key
        ttl      - int, seconds to keep the cached value
        producer - zero-arg callable returning a JSON-serialisable value
    Output:
        the cached value when present and fresh, otherwise producer()'s result
    Details:
        Read-through cache. Bypassed under Flask TESTING so mocked producers stay
        deterministic. Any Redis failure (read or write) degrades to calling the
        producer directly and is logged at WARNING — the caller never sees an
        error from the cache layer.
    """
    from flask import current_app, has_app_context
    if has_app_context() and current_app.config.get("TESTING"):
        return producer()

    r = None
    try:
        r = get_redis()
        raw = r.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        logger.warning("cached_json: cache read failed for %s", key, exc_info=True)
        r = None

    value = producer()

    if r is not None:
        try:
            r.setex(key, ttl, json.dumps(value))
        except Exception:
            logger.warning("cached_json: cache write failed for %s", key, exc_info=True)

    return value


if __name__ == "__main__":
    pass
