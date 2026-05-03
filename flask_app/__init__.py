"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Flask application factory. Initialises extensions and registers blueprints.
"""
# Imports
import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from authlib.integrations.flask_client import OAuth

# Globals
db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
oauth = OAuth()


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
    oauth.init_app(app)

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
    from flask_app.models.user import User                     # noqa: F401
    from flask_app.models.search_history import SearchHistory  # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget  # noqa: F401
    from flask_app.models.crawl_job import CrawlJob            # noqa: F401

    from flask_app.routes.auth import auth_bp
    from flask_app.routes.search import search_bp
    from flask_app.routes.admin import admin_bp
    from flask_app.routes.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp)

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
