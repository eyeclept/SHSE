"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    User model. Stores credentials, role, and optional SSO identity.
    Roles: admin (full access) | user (search only).
"""
# Imports
import bcrypt as _bcrypt
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

    def set_password(self, password):
        """
        Input: plaintext password string
        Output: None (sets self.password_hash)
        Details:
            Hashes password with bcrypt (random salt per call) and stores the
            result as a UTF-8 string in password_hash.
        """
        self.password_hash = _bcrypt.hashpw(
            password.encode(), _bcrypt.gensalt()
        ).decode()

    def check_password(self, password):
        """
        Input: plaintext password string
        Output: bool
        Details:
            Returns True if password matches the stored bcrypt hash.
            Returns False when password_hash is not set.
        """
        if not self.password_hash:
            return False
        return _bcrypt.checkpw(password.encode(), self.password_hash.encode())


if __name__ == "__main__":
    pass
