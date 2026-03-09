"""
Author: Richard Baldwin
Date:   2024
Email: eyeclept@pm.me

Description: Authentication utilities - password hashing, OIDC, SSO
"""


def hash_password(password):
    """
    Input: password (str) - plaintext password
    Output: str - bcrypt hash
    Details: Hashes password using bcrypt for storage in MariaDB
    """
    pass


def verify_password(password, password_hash):
    """
    Input: password (str) - plaintext password, password_hash (str) - stored hash
    Output: bool - True if password matches hash
    Details: Verifies bcrypt hash
    """
    pass


def get_oidc_client():
    """
    Input: None
    Output: Authlib OIDC client instance
    Details: Initializes OIDC client for SSO provider
    """
    pass


def exchange_authorization_code(code, state):
    """
    Input: code (str) - authorization code from SSO provider, state (str) - state param
    Output: dict - user claims from OIDC token (sub, email, groups, etc.)
    Details: Exchanges authorization code for token with SSO provider
    """
    pass


def map_sso_claims_to_role(claims):
    """
    Input: claims (dict) - OIDC token claims
    Output: str - role ('admin' or 'user')
    Details: Maps SSO claims (groups, etc.) to SHSE role
    """
    pass
