"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Admin user/account administration: user list, role promote/demote, and the
    cross-user API-token audit/revoke views. Registers its routes on the shared
    ``admin_bp``.
"""
# Imports
import logging

from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user

from flask_app.routes.admin import admin_bp
from flask_app.routes.admin._shared import admin_required

# Globals
logger = logging.getLogger(__name__)


# ── Users ──────────────────────────────────────────────────────────────────

@admin_bp.route("/users")
@admin_required
def users():
    """
    Input: None
    Output: rendered user list page with promote/demote buttons
    Details:
        Lists all User rows ordered by username. Admins can promote any user
        to admin role or demote any admin to user role (self-demote blocked).
    """
    from flask_app import db
    from flask_app.models.user import User

    all_users = db.session.query(User).order_by(User.username).all()
    return render_template("admin/users.html", users=all_users)


@admin_bp.route("/users/<int:user_id>/promote", methods=["POST"])
@admin_required
def promote_user(user_id):
    """
    Input: user_id URL param
    Output: redirect to users list
    Details:
        Sets role='admin' for the target user. No-op if already admin.
    """
    from flask_app import db
    from flask_app.models.user import User

    u = db.session.get(User, user_id)
    if u is None:
        abort(404)
    u.role = "admin"
    db.session.commit()
    logger.info("promote_user: user_id=%s promoted to admin by user_id=%s", u.id, current_user.id)
    flash(f"'{u.username}' promoted to admin.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/demote", methods=["POST"])
@admin_required
def demote_user(user_id):
    """
    Input: user_id URL param
    Output: redirect to users list
    Details:
        Sets role='user' for the target user. Blocks self-demote.
    """
    from flask_app import db
    from flask_app.models.user import User

    u = db.session.get(User, user_id)
    if u is None:
        abort(404)
    if u.id == current_user.id:
        flash("You cannot demote yourself.", "error")
        return redirect(url_for("admin.users"))
    u.role = "user"
    db.session.commit()
    logger.info("demote_user: user_id=%s demoted to user by user_id=%s", u.id, current_user.id)
    flash(f"'{u.username}' demoted to user.", "success")
    return redirect(url_for("admin.users"))


# ── API Tokens ──────────────────────────────────────────────────────────────

@admin_bp.route("/tokens")
@admin_required
def admin_tokens():
    """
    Input: None
    Output: rendered token audit page listing all ApiToken rows joined to User
    Details:
        Admin-only view that shows every token across all users so admins can
        audit and revoke tokens as needed.
    """
    from flask_app import db
    from flask_app.models.api_token import ApiToken
    from flask_app.models.user import User  # noqa: F401 — ApiToken.user relationship

    tokens = (
        db.session.execute(
            db.select(ApiToken).order_by(ApiToken.id.desc())
        )
        .scalars()
        .all()
    )
    return render_template("admin/tokens.html", tokens=tokens)


@admin_bp.route("/tokens/<int:token_id>/revoke", methods=["POST"])
@admin_required
def admin_revoke_token(token_id):
    """
    Input: token_id URL param
    Output: redirect to /admin/tokens
    Details:
        Sets revoked_at to the current UTC time on any token regardless of owner.
        Admin-only operation for emergency revocation.
    """
    from datetime import datetime
    from flask_app import db
    from flask_app.models.api_token import ApiToken

    token = db.session.get(ApiToken, token_id)
    if token is None:
        abort(404)
    token.revoked_at = datetime.utcnow()
    db.session.commit()
    logger.info(
        "admin_revoke_token: token_id=%s user_id=%s revoked by admin user_id=%s",
        token.id, token.user_id, current_user.id,
    )
    flash(f"Token '{token.name}' revoked.", "success")
    return redirect(url_for("admin.admin_tokens"))
