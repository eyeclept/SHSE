"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Shared helpers for Celery task modules.
"""
# Imports
import logging

# Globals
logger = logging.getLogger(__name__)

# Functions
def _build_app_context():
    """
    Input: None
    Output: (Flask app, db) — used by tasks when no injected session
    Details:
        Deferred import avoids circular import at module load time.
    """
    from flask_app import create_app, db as _db
    return create_app(), _db
