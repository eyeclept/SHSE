"""
Author: Richard Baldwin
Date:   2024
Email: eyeclept@pm.me

Description: Route blueprints initialization
"""

from flask import Blueprint

search_bp = Blueprint('search', __name__, url_prefix='/')
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
