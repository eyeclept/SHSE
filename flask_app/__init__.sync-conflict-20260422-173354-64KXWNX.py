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

# Globals
db = SQLAlchemy()
login_manager = LoginManager()

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

    from flask_app.routes.auth import auth_bp
    from flask_app.routes.search import search_bp
    from flask_app.routes.admin import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    return app


if __name__ == "__main__":
    create_app().run()
