"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Auth blueprint. Handles login, logout, registration, and first-run setup.
    Local password auth is on by default. SSO (OIDC) is optional via SSO_ENABLED.
"""
# Imports
from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from flask_login import login_user, logout_user
from flask_app import db, oauth
from flask_app.models.user import User

# Globals
auth_bp = Blueprint("auth", __name__)

# Functions
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    Input: username, password (form POST)
    Output: redirect on success, re-render form with 401 on failure
    Details:
        Validates credentials against MariaDB bcrypt hash.
        Creates Flask-Login session on success.
    """
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.session.execute(
            db.select(User).filter_by(username=username)
        ).scalar_one_or_none()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("search.index"))
        return render_template("login.html", error="Invalid credentials"), 401
    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    """
    Input: None
    Output: redirect to login page
    Details:
        Clears the Flask-Login session.
    """
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """
    Input: username, password (form POST)
    Output: redirect on success, re-render form on failure
    Details:
        Creates a new user with role 'user'. Admin accounts are set manually.
        Returns 400 if username is already taken.
    """
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            return render_template("register.html", error="Username and password required"), 400
        existing = db.session.execute(
            db.select(User).filter_by(username=username)
        ).scalar_one_or_none()
        if existing:
            return render_template("register.html", error="Username already taken"), 400
        user = User(username=username, role="user")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for("auth.login"))
    return render_template("register.html")


@auth_bp.route("/setup", methods=["GET", "POST"])
def setup():
    """
    Input: username, password (form POST)
    Output: redirect to login on success, redirect to login if admin already exists
    Details:
        First-run only. Creates the initial admin account.
        Redirects to login if an admin already exists.
    """
    admin_exists = db.session.execute(
        db.select(User).filter_by(role="admin")
    ).scalar_one_or_none() is not None
    if admin_exists:
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            return render_template("setup.html", error="Username and password required"), 400
        user = User(username=username, role="admin")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for("auth.login"))
    return render_template("setup.html")


@auth_bp.route("/sso/login")
def sso_login():
    """
    Input: None
    Output: redirect to OIDC provider authorization endpoint
    Details:
        Only active when SSO_ENABLED=true. Returns 404 otherwise.
    """
    if not current_app.config.get("SSO_ENABLED"):
        abort(404)
    redirect_uri = url_for("auth.sso_callback", _external=True)
    return oauth.oidc.authorize_redirect(redirect_uri)


def _sso_role(userinfo):
    """
    Input: userinfo dict from OIDC token
    Output: 'admin' if user is in the configured admin group, else 'user'
    Details:
        Reads SSO_ADMIN_GROUP from app config (default 'admin').
        Checks the standard OIDC 'groups' claim (list of strings).
    """
    admin_group = current_app.config.get("SSO_ADMIN_GROUP", "admin")
    return "admin" if admin_group in userinfo.get("groups", []) else "user"


@auth_bp.route("/sso/callback")
def sso_callback():
    """
    Input: OIDC callback params (code, state) via query string
    Output: redirect to search page on success
    Details:
        Exchanges code for token, extracts userinfo from id_token.
        Creates a new user on first SSO login keyed on 'sub'.
        Role is derived from OIDC groups claim on every login so that
        provider-side group changes take effect on the next sign-in.
        Only active when SSO_ENABLED=true.
    """
    if not current_app.config.get("SSO_ENABLED"):
        abort(404)
    token = oauth.oidc.authorize_access_token()
    userinfo = token.get("userinfo", {})
    sub = userinfo.get("sub")
    if not sub:
        abort(400)
    role = _sso_role(userinfo)
    user = db.session.execute(
        db.select(User).filter_by(sso_identity=sub)
    ).scalar_one_or_none()
    if not user:
        username = userinfo.get("preferred_username") or userinfo.get("email") or sub
        user = User(username=username, role=role, sso_identity=sub)
        db.session.add(user)
    else:
        user.role = role
    db.session.commit()
    login_user(user)
    return redirect(url_for("search.index"))


if __name__ == "__main__":
    pass
