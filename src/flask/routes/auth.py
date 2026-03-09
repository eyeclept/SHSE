"""
Author: Richard Baldwin
Date:   2024
Email: eyeclept@pm.me

Description: Authentication routes - login, registration, SSO, logout
"""


def login_view():
    """
    Input: username, password from form
    Output: Redirect to dashboard on success, error message on failure
    Details: Supports both local password auth and SSO OIDC flow
    """
    pass


def register_view():
    """
    Input: username, password from form
    Output: Redirect to login on success
    Details: Only available if AUTH_LOCAL_ENABLED=true; creates user in MariaDB
    """
    pass


def logout_view():
    """
    Input: None (uses current session)
    Output: Redirect to login page
    Details: Clears Flask-Login session
    """
    pass


def sso_callback_view():
    """
    Input: OIDC authorization code (from SSO provider redirect)
    Output: Redirect to dashboard on success
    Details: Provisions/updates user in MariaDB from OIDC token claims
    """
    pass
