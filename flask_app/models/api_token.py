"""
Author: Richard Baldwin
Date:   2026
Email:  eyeclept@pm.me

Description:
    ApiToken model.  Stores HMAC-hashed API tokens for Bearer authentication.
    Raw tokens are generated with a "shse_" prefix and never stored; only the
    HMAC-SHA256 hash is persisted.  Tokens can be revoked or given an expiry.
"""
# Imports
import logging
import secrets
from datetime import datetime

from flask_app import db

# Globals
logger = logging.getLogger(__name__)


# Functions
class ApiToken(db.Model):
    """
    Input: None
    Output: ORM model mapped to the api_tokens table
    Details:
        token_hash stores a 64-char hex HMAC-SHA256 digest; the raw token is
        shown to the user once and never persisted.
        is_active checks revoked_at and expires_at to determine validity.
    """
    __tablename__ = "api_tokens"

    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(128), nullable=False)
    token_hash   = db.Column(db.String(64), unique=True, nullable=False)
    user_id      = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime, nullable=True)
    expires_at   = db.Column(db.DateTime, nullable=True)
    revoked_at   = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", backref="api_tokens")

    @property
    def is_active(self) -> bool:
        """
        Input:  None
        Output: True if the token is valid (not revoked and not expired)
        Details:
            Returns False if revoked_at is set.
            Returns False if expires_at is set and is in the past.
            Otherwise returns True.
        """
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and datetime.utcnow() > self.expires_at:
            return False
        return True

    @classmethod
    def generate(cls, name: str, user) -> tuple:
        """
        Input:  name — human-readable label for the token
                user — User ORM instance that owns the token
        Output: (ApiToken instance, raw_token string)
        Details:
            Generates a cryptographically random raw token with "shse_" prefix.
            Stores only the HMAC-SHA256 hash; the raw token is returned once
            and must be shown to the user immediately — it cannot be recovered.
        """
        from flask_app.services.token_backend import get_backend

        raw = "shse_" + secrets.token_urlsafe(32)
        token_hash = get_backend().hmac(raw)
        token = cls(name=name, token_hash=token_hash, user_id=user.id)
        logger.info("ApiToken.generate: new token name=%s user_id=%s", name, user.id)
        return token, raw

    @classmethod
    def verify(cls, raw_token: str):
        """
        Input:  raw_token — plaintext Bearer token from the Authorization header
        Output: ApiToken instance if valid and active; None otherwise
        Details:
            Computes the HMAC of raw_token and looks up by token_hash.
            Returns None if no matching row exists or if is_active is False.
        """
        from flask_app import db
        from flask_app.services.token_backend import get_backend

        try:
            token_hash = get_backend().hmac(raw_token)
            token = db.session.execute(
                db.select(cls).filter_by(token_hash=token_hash)
            ).scalar_one_or_none()
            if token is None:
                return None
            if not token.is_active:
                logger.info(
                    "ApiToken.verify: inactive token id=%s user_id=%s", token.id, token.user_id
                )
                return None
            return token
        except Exception:
            logger.exception("ApiToken.verify: unexpected error during token lookup")
            return None


if __name__ == "__main__":
    pass
