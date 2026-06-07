"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Flask application factory. Initialises extensions and registers blueprints.
"""
# Imports
import hashlib
import logging
import os
from datetime import timedelta
from logging.handlers import RotatingFileHandler

from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from authlib.integrations.flask_client import OAuth

# Globals
db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
oauth = OAuth()
csrf = CSRFProtect()

# Throttle window (seconds) for persisting ApiToken.last_used_at — avoids a DB
# write on every authenticated API request.
_TOKEN_LAST_USED_THROTTLE = 60


def _limiter_key():
    """
    Input:  None (reads Flask request context)
    Output: string key used by Flask-Limiter for rate-limit bucketing
    Details:
        Token-authenticated requests are keyed by a truncated MD5 of the
        Authorization header so that all requests sharing a token share a
        bucket regardless of source IP (useful behind proxies or Tor).
        All other requests fall back to the remote IP address.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer shse_"):
        return "token:" + hashlib.md5(auth.encode()).hexdigest()[:16]
    return get_remote_address()


def is_loopback() -> bool:
    """
    Input:  None (reads Flask request context)
    Output: True when the request originates from the loopback interface
    Details:
        Used as exempt_when on rate-limited routes.  All external traffic
        arrives via Nginx (which is not on loopback), so only internal
        callers — test runners, CLI, container-to-container — are exempted.
    """
    return get_remote_address() in ("127.0.0.1", "::1")


limiter = Limiter(key_func=_limiter_key)


@login_manager.user_loader
def load_user(user_id):
    """
    Input: user_id string (from session)
    Output: User instance or None
    Details:
        Required by Flask-Login. Lazy import avoids circular dependency.
    """
    from flask_app.models.user import User
    return db.session.get(User, int(user_id))


@login_manager.request_loader
def load_user_from_request(request):
    """
    Input: Flask request object
    Output: User if valid Bearer token; None to fall back to session auth
    Details:
        Authenticates API requests via Bearer token without creating a session.
        Checks api.enabled system setting; skips token auth if disabled.
        Updates last_used_at on each successful auth.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer shse_"):
        return None
    # Deferred imports to avoid circular dependency at module load
    try:
        from flask_app.models.api_token import ApiToken
        from flask_app.models.system_setting import SystemSetting
        enabled = db.session.get(SystemSetting, "api.enabled")
        if enabled and enabled.value == "0":
            return None
        raw_token = auth[7:]   # strip "Bearer "
        token = ApiToken.verify(raw_token)
        if token is None:
            return None
        from datetime import datetime
        now = datetime.utcnow()
        # Only persist last_used_at when the stored value is stale by more than
        # the throttle window, so a burst of API calls is not one commit each.
        if token.last_used_at is None or (now - token.last_used_at).total_seconds() > _TOKEN_LAST_USED_THROTTLE:
            token.last_used_at = now
            db.session.commit()
        import logging as _logging
        _logging.getLogger(__name__).info(
            "api token auth: user_id=%s token_id=%s path=%s",
            token.user_id, token.id, request.path,
        )
        return token.user
    except Exception:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "request_loader: token auth failed", exc_info=True
        )
        return None

# Functions
def create_app():
    """
    Input: None
    Output: Flask app instance
    Details:
        Creates and configures the Flask application, initialises extensions,
        and registers the auth, search, and admin blueprints.
    """
    app = Flask(__name__)
    app.config.from_object("flask_app.config.Config")

    # Session security hardening (SEC-002, SEC-004)
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    app.config.setdefault("SESSION_COOKIE_SECURE", not app.testing)
    app.config.setdefault("PERMANENT_SESSION_LIFETIME", timedelta(hours=24))

    log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    _fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    _handler = RotatingFileHandler(
        os.path.join(log_dir, "flask.log"), maxBytes=5 * 1024 * 1024, backupCount=3
    )
    _handler.setFormatter(logging.Formatter(_fmt))
    logging.root.setLevel(logging.INFO)
    logging.root.addHandler(_handler)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    oauth.init_app(app)
    limiter.init_app(app)
    csrf.init_app(app)

    if app.config.get("SSO_ENABLED"):
        oauth.register(
            name="oidc",
            server_metadata_url=app.config["SSO_PROVIDER_URL"] + "/.well-known/openid-configuration",
            client_id=app.config["SSO_CLIENT_ID"],
            client_secret=app.config["SSO_CLIENT_SECRET"],
            client_kwargs={"scope": "openid email profile"},
        )

    # Import all models before blueprints so SQLAlchemy can resolve
    # relationship strings (e.g. User.search_history → SearchHistory)
    # without hitting an InvalidRequestError on first mapper access.
    from flask_app.models.user import User                         # noqa: F401
    from flask_app.models.search_history import SearchHistory      # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget      # noqa: F401
    from flask_app.models.crawl_job import CrawlJob                # noqa: F401
    from flask_app.models.system_setting import SystemSetting      # noqa: F401
    from flask_app.models.api_token import ApiToken                # noqa: F401

    from flask_app.routes.auth import auth_bp
    from flask_app.routes.search import search_bp
    from flask_app.routes.admin import admin_bp
    from flask_app.routes.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp)
    csrf.exempt(api_bp)

    _init_logger = logging.getLogger(__name__)

    # Ensure a default admin account exists on first boot.
    # Username: admin  Password: admin  (change after first login)
    with app.app_context():
        try:
            if not db.session.execute(
                db.select(User).filter_by(role="admin")
            ).scalar_one_or_none():
                default_admin = User(username="admin", role="admin")
                default_admin.set_password("admin")
                db.session.add(default_admin)
                db.session.commit()
        except Exception:
            _init_logger.exception("Default admin seeding failed")

    return app


if __name__ == "__main__":
    create_app().run()
