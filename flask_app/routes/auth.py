"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Auth blueprint. Handles login, logout, registration, and first-run setup.
    Local password auth is on by default. SSO (OIDC) is optional via SSO_ENABLED.
"""
# Imports
import logging

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from flask_login import login_user, logout_user
from flask_app import db, oauth
from flask_app.models.user import User

# Globals
auth_bp = Blueprint("auth", __name__)
logger = logging.getLogger(__name__)

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
            from flask import session
            from flask_app.models.webauthn_credential import WebAuthnCredential

            # Force password change if still using the default admin/admin credential
            default_pw_warning = user.username == "admin" and user.check_password("admin")

            # Route to 2FA challenge if enrolled
            if getattr(user, "totp_enabled", False):
                session["pre_2fa_user_id"] = user.id
                return redirect(url_for("auth.totp_challenge"))

            has_webauthn = db.session.execute(
                db.select(WebAuthnCredential).filter_by(user_id=user.id)
            ).scalars().first() is not None
            if has_webauthn:
                session["pre_2fa_user_id"] = user.id
                return redirect(url_for("auth.webauthn_challenge"))

            login_user(user)
            if default_pw_warning:
                from flask import flash
                flash(
                    "You are using the default password. Please change it now.",
                    "error",
                )
                return redirect(url_for("search.settings"))
            return redirect(url_for("search.home"))
        return render_template(
            "login.html",
            error="Invalid credentials",
            sso_enabled=current_app.config.get("SSO_ENABLED", False),
            smtp_enabled=bool(current_app.config.get("SMTP_HOST", "")),
        ), 401
    return render_template(
        "login.html",
        sso_enabled=current_app.config.get("SSO_ENABLED", False),
        smtp_enabled=bool(current_app.config.get("SMTP_HOST", "")),
    )


@auth_bp.route("/logout", methods=["GET", "POST"])
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
    sso_enabled = current_app.config.get("SSO_ENABLED", False)
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            return render_template("register.html", error="Username and password required",
                                   sso_enabled=sso_enabled), 400
        existing = db.session.execute(
            db.select(User).filter_by(username=username)
        ).scalar_one_or_none()
        if existing:
            return render_template("register.html", error="Username already taken",
                                   sso_enabled=sso_enabled), 400
        user = User(username=username, role="user")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for("auth.login"))
    is_first = db.session.execute(db.select(User)).scalars().first() is None
    return render_template("register.html", is_first=is_first, sso_enabled=sso_enabled)


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
    ).scalars().first() is not None
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
    return redirect(url_for("search.home"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """
    Input: email or username (form POST)
    Output: always renders the same response to prevent user enumeration
    Details:
        Creates a one-time reset token (1-hour TTL) and sends a recovery email
        when the submitted username matches a known user. When SMTP is not
        configured the route still returns 200 but no email is sent.
    """
    from flask_app.config import Config
    smtp_enabled = bool(Config.SMTP_HOST)
    if request.method == "GET":
        return render_template("forgot_password.html", smtp_enabled=smtp_enabled, sent=False)

    from flask_app.models.password_reset_token import PasswordResetToken
    from flask_app.services.email import send_email

    username = request.form.get("username", "").strip()
    user = db.session.execute(
        db.select(User).filter_by(username=username)
    ).scalar_one_or_none()

    if user and user.username:
        token_obj = PasswordResetToken.create_for_user(user.id)
        db.session.add(token_obj)
        db.session.commit()
        reset_url = f"{Config.APP_URL}/reset-password/{token_obj.token}"
        send_email(
            to=username,
            subject="SHSE — Password reset",
            body=f"Reset your password by visiting:\n\n{reset_url}\n\nThis link expires in 1 hour.",
        )
        logger.info("forgot_password: reset token issued for user_id=%s", user.id)

    return render_template("forgot_password.html", smtp_enabled=smtp_enabled, sent=True)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    """
    Input: token (URL path), new_password + confirm_password (form POST)
    Output: renders form on GET; on valid POST resets password and redirects to login
    Details:
        Returns 400 when the token is expired or already used.
        Marks the token as used after a successful password reset.
    """
    from flask_app.models.password_reset_token import PasswordResetToken

    token_obj = db.session.execute(
        db.select(PasswordResetToken).filter_by(token=token)
    ).scalar_one_or_none()

    if token_obj is None or not token_obj.is_valid():
        return render_template("reset_password.html", error="This reset link is invalid or has expired."), 400

    if request.method == "GET":
        return render_template("reset_password.html", token=token)

    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    if not new_password:
        return render_template("reset_password.html", token=token,
                               error="Password cannot be blank."), 400
    if new_password != confirm:
        return render_template("reset_password.html", token=token,
                               error="Passwords do not match."), 400

    user = db.session.get(User, token_obj.user_id)
    user.set_password(new_password)
    token_obj.used = True
    db.session.commit()
    logger.info("reset_password: password reset for user_id=%s", user.id)
    from flask import flash
    flash("Your password has been reset. Please sign in.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/login/2fa", methods=["GET", "POST"])
def totp_challenge():
    """
    Input: code (form POST), pre_2fa_user_id (session)
    Output: renders TOTP challenge page; on valid code completes login
    Details:
        Called after successful password verification when the user has TOTP enabled.
        The pre-auth user ID is stored in the session so the login is not completed
        until the second factor is verified.
    """
    from flask import session
    import pyotp

    user_id = session.get("pre_2fa_user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    user = db.session.get(User, user_id)
    if not user or not user.totp_enabled:
        session.pop("pre_2fa_user_id", None)
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        code = request.form.get("code", "").strip()
        totp = pyotp.TOTP(user.totp_secret)
        if totp.verify(code):
            session.pop("pre_2fa_user_id", None)
            login_user(user)
            return redirect(url_for("search.home"))
        logger.warning("totp_challenge: invalid code for user_id=%s", user_id)
        return render_template("totp_challenge.html", error="Invalid code. Try again."), 401

    return render_template("totp_challenge.html")


@auth_bp.route("/login/webauthn", methods=["GET", "POST"])
def webauthn_challenge():
    """
    Input: assertion JSON (form POST body), pre_2fa_user_id (session)
    Output: renders WebAuthn challenge page; on valid assertion completes login
    Details:
        Called after password verification when the user has a registered WebAuthn
        credential and TOTP is not enabled. Generates a challenge on GET, verifies
        the assertion on POST.
    """
    import json
    from flask import session

    user_id = session.get("pre_2fa_user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    user = db.session.get(User, user_id)
    if not user:
        session.pop("pre_2fa_user_id", None)
        return redirect(url_for("auth.login"))

    from flask_app.models.webauthn_credential import WebAuthnCredential
    credentials = db.session.execute(
        db.select(WebAuthnCredential).filter_by(user_id=user_id)
    ).scalars().all()

    if request.method == "GET":
        import os
        import base64
        challenge = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
        session["webauthn_challenge"] = challenge
        cred_ids = [
            base64.urlsafe_b64encode(c.credential_id).rstrip(b"=").decode()
            for c in credentials
        ]
        return render_template("webauthn_challenge.html", challenge=challenge, cred_ids=cred_ids)

    # POST: verify assertion
    try:
        from webauthn import verify_authentication_response
        from webauthn.helpers.structs import AuthenticationCredential
        from webauthn.helpers.exceptions import InvalidAuthenticationResponse
        from flask_app.config import Config

        body = request.get_json(silent=True) or {}
        auth_cred = AuthenticationCredential.parse_raw(json.dumps(body))
        credential_id_bytes = auth_cred.raw_id

        cred = db.session.execute(
            db.select(WebAuthnCredential).filter_by(
                credential_id=credential_id_bytes, user_id=user_id
            )
        ).scalar_one_or_none()

        if cred is None:
            logger.warning("webauthn_challenge: unknown credential for user_id=%s", user_id)
            return {"error": "Unknown credential"}, 401

        expected_challenge = session.get("webauthn_challenge", "")
        import base64
        rp_id = current_app.config.get("WEBAUTHN_RP_ID", "localhost")
        verification = verify_authentication_response(
            credential=auth_cred,
            expected_challenge=base64.urlsafe_b64decode(expected_challenge + "=="),
            expected_rp_id=rp_id,
            expected_origin=current_app.config.get("WEBAUTHN_ORIGIN", "http://localhost:5000"),
            credential_public_key=cred.public_key,
            credential_current_sign_count=cred.sign_count,
        )
        cred.sign_count = verification.new_sign_count
        db.session.commit()
        session.pop("pre_2fa_user_id", None)
        session.pop("webauthn_challenge", None)
        login_user(user)
        return {"ok": True}
    except Exception:
        logger.exception("webauthn_challenge: assertion verification failed for user_id=%s", user_id)
        return {"error": "Authentication failed"}, 401


@auth_bp.route("/settings/2fa/setup", methods=["GET", "POST"])
def totp_setup():
    """
    Input: code (form POST confirming enrollment)
    Output: GET returns JSON {secret, uri}; POST validates code and enables TOTP
    Details:
        Requires authentication. GET generates a fresh TOTP secret stored
        temporarily in the session. POST verifies the 6-digit code and
        persists the secret + totp_enabled=True.
    """
    from flask import session
    from flask_login import current_user, login_required
    import pyotp

    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))

    if request.method == "GET":
        secret = pyotp.random_base32()
        session["totp_pending_secret"] = secret
        uri = pyotp.TOTP(secret).provisioning_uri(
            name=current_user.username, issuer_name="SHSE"
        )
        return {"secret": secret, "uri": uri}

    secret = session.get("totp_pending_secret")
    if not secret:
        return {"error": "No pending TOTP setup. Reload the page."}, 400

    code = request.form.get("code", "").strip()
    totp = pyotp.TOTP(secret)
    if not totp.verify(code):
        return render_template("totp_setup.html", error="Invalid code. Try again."), 400

    current_user.totp_secret = secret
    current_user.totp_enabled = True
    db.session.commit()
    session.pop("totp_pending_secret", None)
    logger.info("totp_setup: TOTP enrolled for user_id=%s", current_user.id)
    from flask import flash
    flash("Two-factor authentication enabled.", "success")
    return redirect(url_for("search.settings"))


@auth_bp.route("/settings/2fa/disable", methods=["POST"])
def totp_disable():
    """
    Input: current_password (form POST)
    Output: redirect to settings on success, 400 on wrong password
    Details:
        Requires password confirmation before clearing TOTP state.
    """
    from flask_login import current_user

    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))

    current_password = request.form.get("current_password", "")
    if not current_user.check_password(current_password):
        from flask import flash
        flash("Incorrect password. 2FA not disabled.", "error")
        return redirect(url_for("search.settings"))

    current_user.totp_secret = None
    current_user.totp_enabled = False
    db.session.commit()
    logger.info("totp_disable: TOTP disabled for user_id=%s", current_user.id)
    from flask import flash
    flash("Two-factor authentication disabled.", "success")
    return redirect(url_for("search.settings"))


@auth_bp.route("/settings/2fa/webauthn/register", methods=["GET", "POST"])
def webauthn_register():
    """
    Input: registration credential JSON (POST body)
    Output: GET returns registration options JSON; POST verifies and stores credential
    Details:
        Requires authentication. GET generates a WebAuthn registration challenge.
        POST verifies the authenticator response and stores the credential.
    """
    import json, os, base64
    from flask import session
    from flask_login import current_user

    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))

    if request.method == "GET":
        from webauthn import generate_registration_options
        from webauthn.helpers.structs import (
            AuthenticatorSelectionCriteria,
            UserVerificationRequirement,
        )
        rp_id = current_app.config.get("WEBAUTHN_RP_ID", "localhost")
        rp_name = current_app.config.get("WEBAUTHN_RP_NAME", "SHSE")
        options = generate_registration_options(
            rp_id=rp_id,
            rp_name=rp_name,
            user_id=str(current_user.id).encode(),
            user_name=current_user.username,
            authenticator_selection=AuthenticatorSelectionCriteria(
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
        )
        challenge_b64 = base64.urlsafe_b64encode(options.challenge).rstrip(b"=").decode()
        session["webauthn_reg_challenge"] = challenge_b64
        from webauthn.helpers.cose import COSEAlgorithmIdentifier
        pub_key_cred_params = [
            {"type": "public-key", "alg": p.alg.value}
            for p in options.pub_key_cred_params
        ]
        return {
            "challenge": challenge_b64,
            "rp": {"id": options.rp.id, "name": options.rp.name},
            "user": {
                "id": base64.urlsafe_b64encode(options.user.id).rstrip(b"=").decode(),
                "name": options.user.name,
                "displayName": options.user.display_name,
            },
            "pubKeyCredParams": pub_key_cred_params,
            "timeout": options.timeout,
            "attestation": "none",
        }

    # POST: verify registration
    try:
        from webauthn import verify_registration_response
        from webauthn.helpers.structs import RegistrationCredential
        from flask_app.models.webauthn_credential import WebAuthnCredential

        body = request.get_json(silent=True) or {}
        reg_cred = RegistrationCredential.parse_raw(json.dumps(body))
        expected_challenge = session.get("webauthn_reg_challenge", "")
        rp_id = current_app.config.get("WEBAUTHN_RP_ID", "localhost")
        origin = current_app.config.get("WEBAUTHN_ORIGIN", "http://localhost:5000")

        verification = verify_registration_response(
            credential=reg_cred,
            expected_challenge=base64.urlsafe_b64decode(expected_challenge + "=="),
            expected_rp_id=rp_id,
            expected_origin=origin,
        )

        key_name = body.get("name", "Security Key")
        credential = WebAuthnCredential(
            credential_id=verification.credential_id,
            user_id=current_user.id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            aaguid=str(verification.aaguid) if verification.aaguid else None,
            name=key_name[:64],
        )
        db.session.add(credential)
        db.session.commit()
        session.pop("webauthn_reg_challenge", None)
        logger.info("webauthn_register: credential stored for user_id=%s", current_user.id)
        return {"ok": True}
    except Exception:
        logger.exception("webauthn_register: verification failed for user_id=%s", current_user.id)
        return {"error": "Registration failed"}, 400


@auth_bp.route("/settings/2fa/webauthn/<int:credential_id>/remove", methods=["POST"])
def webauthn_remove(credential_id):
    """
    Input: credential_id (URL path), current_password (form POST)
    Output: redirect to settings after removing the credential
    Details:
        Requires password confirmation. Deletes the WebAuthnCredential row.
    """
    from flask_login import current_user
    from flask_app.models.webauthn_credential import WebAuthnCredential

    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))

    current_password = request.form.get("current_password", "")
    if not current_user.check_password(current_password):
        from flask import flash
        flash("Incorrect password. Key not removed.", "error")
        return redirect(url_for("search.settings"))

    cred = db.session.execute(
        db.select(WebAuthnCredential).filter_by(id=credential_id, user_id=current_user.id)
    ).scalar_one_or_none()
    if cred:
        db.session.delete(cred)
        db.session.commit()
        logger.info("webauthn_remove: credential %s removed for user_id=%s", credential_id, current_user.id)
        from flask import flash
        flash("Security key removed.", "success")
    return redirect(url_for("search.settings"))


@auth_bp.route("/theme", methods=["POST"])
def toggle_theme():
    """
    Input: None (reads session['theme'])
    Output: redirect back to referring page
    Details:
        Flips the session theme between light and dark. Called by the hamburger menu.
    """
    from flask import session
    session["theme"] = "dark" if session.get("theme") != "dark" else "light"
    referrer = request.referrer or url_for("search.home")
    return redirect(referrer)


if __name__ == "__main__":
    pass
