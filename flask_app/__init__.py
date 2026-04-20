"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Flask application factory. Initialises extensions and registers blueprints.
"""
# Imports
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from authlib.integrations.flask_client import OAuth

# Globals
db = SQLAlchemy()
login_manager = LoginManager()
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

    db.init_app(app)
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

    from flask_app.routes.auth import auth_bp
    from flask_app.routes.search import search_bp
    from flask_app.routes.admin import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    return app


if __name__ == "__main__":
    create_app().run()
