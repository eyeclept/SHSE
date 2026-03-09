"""
Author: Richard Baldwin
Date:   2024
Email: eyeclept@pm.me

Description: Flask application factory and initialization
"""

from flask import Flask
from src.config.settings import get_config


def create_app(config_name='development'):
    """
    Input: config_name (str) - 'development', 'testing', or 'production'
    Output: Flask application instance
    Details: Creates and configures the Flask app with all blueprints and extensions
    """
    app = Flask(__name__)
    config = get_config(config_name)
    app.config.from_object(config)
    
    # Initialize extensions here
    # db.init_app(app)
    # login_manager.init_app(app)
    
    # Register blueprints
    from src.flask.routes import search_bp, auth_bp, admin_bp
    app.register_blueprint(search_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    
    return app
