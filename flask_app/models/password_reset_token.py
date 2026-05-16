"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    PasswordResetToken model. One-time tokens for email-based password recovery.
    Tokens expire after 1 hour and are single-use.
"""
# Imports
import uuid
from datetime import datetime, timezone, timedelta

from flask_app import db

# Globals

# Functions
class PasswordResetToken(db.Model):
    """
    Input: None
    Output: ORM model mapped to the password_reset_tokens table
    Details:
        token — UUID4 string used in the reset URL.
        user_id — FK to users.id.
        expires_at — UTC datetime; token invalid after this time.
        used — True once the token has been consumed.
    """
    __tablename__ = "password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)

    user = db.relationship("User", backref="reset_tokens")

    @classmethod
    def create_for_user(cls, user_id: int, ttl_hours: int = 1) -> "PasswordResetToken":
        """
        Input: user_id, optional TTL in hours (default 1)
        Output: new PasswordResetToken instance (not yet committed)
        Details:
            Generates a UUID4 token with an expiry set to now + ttl_hours.
        """
        return cls(
            user_id=user_id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
        )

    def is_valid(self) -> bool:
        """
        Input: None
        Output: True if the token has not been used and has not expired
        Details:
            Handles both timezone-aware (MariaDB) and naive (SQLite test) datetimes.
        """
        now = datetime.now(timezone.utc)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return not self.used and now < expires


if __name__ == "__main__":
    pass
