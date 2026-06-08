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
from werkzeug.middleware.proxy_fix import ProxyFix
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

# SECRET_KEY values that must never sign real session cookies: the empty string,
# the in-code fallback (config.py), and the .env.example placeholder. create_app
# refuses to boot (outside testing) when SECRET_KEY is one of these.
_WEAK_SECRET_KEYS = {"", "change-me", "change-me-to-a-long-random-string"}

# Hosts treated as local-only. A passwordless Redis bound to one of these is a
# development convenience; a passwordless Redis on any other (network-reachable)
# host is an unauthenticated broker/cache and is refused at startup.
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


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

    # Refuse to boot outside testing with a missing or placeholder SECRET_KEY.
    # A known signing key lets anyone forge session cookies, which is a direct
    # privilege-escalation path (an attacker can mint an admin session). Failing
    # fast here turns a silent insecure default into an obvious deploy error.
    _secret = app.config.get("SECRET_KEY", "")
    if not app.testing and _secret in _WEAK_SECRET_KEYS:
        raise RuntimeError(
            "SECRET_KEY is unset or a known placeholder value. Generate a strong "
            "random key and set it in .env before starting, e.g. "
            "`python -c \"import secrets; print(secrets.token_hex(32))\"`. "
            "Refusing to boot with a forgeable session-signing key."
        )

    # Refuse to boot outside testing when Redis is network-reachable but has no
    # password. Redis is the Celery broker, so an unauthenticated, LAN-reachable
    # instance lets anyone inject tasks (code execution on the worker), read the
    # cache, or flush data. A blank password is allowed only for a loopback bind
    # (development). Pair with --requirepass in docker-compose.services.yml.
    _redis_host = app.config.get("REDIS_HOST", "")
    _redis_pw = app.config.get("REDIS_PASSWORD", "")
    if not app.testing and not _redis_pw and _redis_host not in _LOOPBACK_HOSTS:
        raise RuntimeError(
            f"REDIS_PASSWORD is empty but Redis is bound to a non-loopback host "
            f"({_redis_host!r}). An unauthenticated, network-reachable Redis is the "
            "Celery broker — anyone on the network could inject tasks or flush data. "
            "Set a strong REDIS_PASSWORD in .env and --requirepass on the Redis "
            "container before starting."
        )

    # Behind Nginx: trust exactly one proxy hop so request.remote_addr and the
    # URL scheme reflect the real client, not the Nginx container IP. The IP-keyed
    # login rate limit (_limiter_key) and every request.remote_addr audit log
    # depend on this. Nginx must set X-Forwarded-For and X-Forwarded-Proto
    # (see nginx/nginx.conf). Trusting exactly one hop prevents clients from
    # spoofing X-Forwarded-For through the proxy.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    # Session security hardening (SEC-002, SEC-004)
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    app.config.setdefault("SESSION_COOKIE_SECURE", not app.testing)
    app.config.setdefault("PERMANENT_SESSION_LIFETIME", timedelta(hours=24))

    # Attach the rotating file handler once per process. create_app() can run
    # more than once (the test suite; a Celery worker rebuilding its app), and
    # without this guard each call stacked another handler on the root logger —
    # every log line written N times, file handles leaked, rotation churned.
    log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.abspath(os.path.join(log_dir, "flask.log"))
    _already = any(
        isinstance(h, RotatingFileHandler)
        and getattr(h, "baseFilename", None) == log_path
        for h in logging.root.handlers
    )
    if not _already:
        _fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
        _handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3)
        _handler.setFormatter(logging.Formatter(_fmt))
        logging.root.addHandler(_handler)
    logging.root.setLevel(logging.INFO)

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

    # No default admin is seeded. A fixed admin/admin account is a standing,
    # network-reachable foothold until an operator changes it. Instead, the first
    # run is handled by the /setup flow: when the user table is empty, the login
    # route funnels to /setup so an operator interactively creates the initial
    # admin with their own credentials (see flask_app/routes/auth.py:login/setup).

    return app


if __name__ == "__main__":
    create_app().run()
