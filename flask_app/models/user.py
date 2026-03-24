"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    User model. Stores credentials, role, and optional SSO identity.
    Roles: admin (full access) | user (search only).
"""
# Imports
from flask_login import UserMixin
from flask_app import db

# Globals

# Functions
class User(UserMixin, db.Model):
    """
    Input: None
    Output: ORM model mapped to the users table
    Details:
        password_hash stores a bcrypt hash.
        sso_identity stores the OIDC subject claim when SSO is enabled.
    """
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.Enum("admin", "user"), nullable=False, default="user")
    sso_identity = db.Column(db.String(256))

    search_history = db.relationship("SearchHistory", backref="user", lazy=True)


if __name__ == "__main__":
    pass
