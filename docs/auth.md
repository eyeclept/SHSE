# SHSE - Authentication

## Route Reference

| Method | Path | Blueprint | Auth required | Description |
|---|---|---|---|---|
| GET / POST | `/login` | auth | No | Local username/password login |
| GET / POST | `/logout` | auth | No | Clear session and redirect to login |
| GET / POST | `/register` | auth | No | Create account with role `user` |
| GET / POST | `/setup` | auth | No | First-run admin creation (redirects if admin exists) |
| POST | `/theme` | auth | No | Toggle session theme between light and dark |
| GET | `/sso/login` | auth | No | Initiate OIDC SSO flow (requires `SSO_ENABLED=true`) |
| GET | `/sso/callback` | auth | No | OIDC callback - exchange code, create/sync user |
| GET / POST | `/admin/*` | admin | admin role | All admin routes enforced by `@admin_required` |

### Login (`POST /login`)

Accepts `username` and `password` form fields. Validates credentials against the bcrypt hash stored in `users.password_hash`. On success calls `login_user()` and redirects to the search page. Returns 401 on failure.

### Registration (`POST /register`)

Creates a user with `role = 'user'`. Returns 400 if the username is already taken or if either field is empty.

### Default admin account

A default admin account (`admin` / `admin`) is created automatically when the Flask app starts for the first time and no admin exists. On first login with these credentials, the app redirects to `/settings` with a warning to change the password.

### Manual admin creation (`GET/POST /setup`)

Fallback route for manually creating an admin if the default account has been deleted. If an admin account already exists, redirects immediately to `/login` without rendering the form.

---

## Session Lifecycle

SHSE uses Flask-Login for session management backed by a signed browser cookie.

1. **Login** - `login_user(user)` writes the user's primary key into the session cookie as `_user_id`.
2. **Request** - `@login_manager.user_loader` re-loads the `User` row from MariaDB on every request.
3. **Logout** - `logout_user()` removes `_user_id` from the session.
4. **Unauthenticated access** - Flask-Login redirects to `/login` when a protected route is hit without a session. The admin blueprint additionally returns 403 for authenticated non-admin users.

The `LOGIN_DISABLED` config flag is not set; every request to `/admin/*` is subject to the `@admin_required` decorator check.

---

## Role Model

SHSE has two roles stored in `users.role` (ENUM `'admin'`, `'user'`):

| Role | Capabilities |
|---|---|
| `user` | Search, view own history, update own settings |
| `admin` | Everything above, plus admin UI: health checks, crawler config, job management, index wipe |

### Assignment rules

| Path | Role assigned |
|---|---|
| `POST /register` | Always `user` |
| `POST /setup` | Always `admin` |
| `GET /sso/callback` (first login) | Derived from OIDC `groups` claim (see SSO section) |
| `GET /sso/callback` (repeat login) | Re-derived from `groups` claim - syncs any provider-side changes |

### `@admin_required` decorator

Defined in `flask_app/routes/admin.py`. Applied to all routes in the admin blueprint.

- Unauthenticated request → 302 redirect to `/login`
- Authenticated non-admin → 403 Forbidden
- Authenticated admin → passes through

---

## SSO Configuration

OIDC SSO is disabled by default. Set `SSO_ENABLED=true` in `.env` to activate it.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `SSO_ENABLED` | `false` | Enable OIDC SSO routes |
| `SSO_PROVIDER_URL` | _(empty)_ | Base URL of the OIDC provider (discovery appended automatically) |
| `SSO_CLIENT_ID` | _(empty)_ | OAuth2 client ID registered with the provider |
| `SSO_CLIENT_SECRET` | _(empty)_ | OAuth2 client secret |
| `SSO_ADMIN_GROUP` | `admin` | OIDC `groups` claim value that grants admin role |

### Flow

1. User visits `/sso/login` → redirected to the provider's authorization endpoint.
2. Provider redirects back to `/sso/callback?code=...&state=...`.
3. SHSE exchanges the code for a token via Authlib.
4. The `sub` claim from `userinfo` is used as the stable identity key (`users.sso_identity`).
5. If no matching user exists, a new row is created with `username` from `preferred_username` (falling back to `email`, then `sub`).
6. Role is derived from the `groups` claim in `userinfo`:
   - If `SSO_ADMIN_GROUP` (default `"admin"`) is present in `groups` → `role = 'admin'`
   - Otherwise → `role = 'user'`
7. For existing users, the role is updated on every login so provider-side group changes take effect immediately on the next sign-in.
8. `login_user()` is called and the user is redirected to the search page.

### Disabling local auth

Set `AUTH_LOCAL_ENABLED=false` in `.env` to prevent local password login. SSO-only mode is intended for environments where all users are managed by the OIDC provider.
