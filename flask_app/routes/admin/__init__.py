"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Admin blueprint package. Provides crawl management, index controls, job
    status, system health indicators, and crawler config editing. All routes
    require admin role; enforced by @admin_required (see _shared.py).

    This package is a thin controller: it defines the single ``admin_bp``
    Blueprint and then imports the per-concern modules so each registers its
    routes on that same blueprint object. The previous single 1197-line
    admin.py was split by concern into config/targets/jobs/users/health; URLs,
    methods, endpoint names (admin.*), and behavior are unchanged.
"""
# Imports
import logging

from flask import Blueprint

# Globals
admin_bp = Blueprint("admin", __name__)
logger = logging.getLogger(__name__)

# Import the per-concern route modules AFTER admin_bp exists so each can do
# `from flask_app.routes.admin import admin_bp` and attach its @admin_bp.route
# handlers to the shared object. Imported for their side effects (route
# registration); the noqa keeps linters from flagging the unused names.
from flask_app.routes.admin import config   # noqa: E402,F401
from flask_app.routes.admin import targets  # noqa: E402,F401
from flask_app.routes.admin import jobs     # noqa: E402,F401
from flask_app.routes.admin import users    # noqa: E402,F401
from flask_app.routes.admin import health   # noqa: E402,F401
