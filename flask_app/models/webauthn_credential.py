"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    WebAuthnCredential model. Stores FIDO2/WebAuthn public-key credentials
    registered by users for hardware second-factor authentication (YubiKey,
    SoloKey, etc.).
"""
# Imports
from datetime import datetime, timezone

from flask_app import db

# Globals

# Functions
class WebAuthnCredential(db.Model):
    """
    Input: None
    Output: ORM model mapped to the webauthn_credentials table
    Details:
        credential_id — raw bytes of the credential ID from the authenticator.
        public_key — CBOR-encoded COSE public key bytes.
        sign_count — monotonically increasing counter; checked on each assertion.
        aaguid — authenticator AAGUID (optional).
        name — user-assigned label for the key.
    """
    __tablename__ = "webauthn_credentials"

    id = db.Column(db.Integer, primary_key=True)
    credential_id = db.Column(db.LargeBinary(255), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    public_key = db.Column(db.LargeBinary(1024), nullable=False)
    sign_count = db.Column(db.Integer, nullable=False, default=0)
    aaguid = db.Column(db.String(36), nullable=True)
    name = db.Column(db.String(64), nullable=False, default="Security Key")
    registered_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    user = db.relationship("User", backref="webauthn_credentials")


if __name__ == "__main__":
    pass
