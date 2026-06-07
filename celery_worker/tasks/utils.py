"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Shared helpers for Celery task modules.
"""
# Imports
import logging
import threading

# Globals
logger = logging.getLogger(__name__)

# One Flask app per worker process. create_app() is expensive (registers all
# blueprints, runs default-admin seeding, and attaches a RotatingFileHandler to
# the root logger) and was previously rebuilt on every task, leaking a log
# handler each time. Build it once and reuse it.
_app = None
_app_lock = threading.Lock()


# Functions
def _build_app_context():
    """
    Input: None
    Output: (Flask app, db) — used by tasks when no injected session
    Details:
        Returns a process-wide singleton Flask app (built once via create_app)
        plus the shared db handle. Thread-safe via double-checked locking.
        Deferred import avoids circular import at module load time.
    """
    global _app
    from flask_app import db as _db
    if _app is not None:
        return _app, _db
    with _app_lock:
        if _app is None:
            from flask_app import create_app
            _app = create_app()
    return _app, _db
