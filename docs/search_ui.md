# SHSE - Search UI

---

## Page Routes

| Method | Path | Blueprint | Description |
|---|---|---|---|
| GET | `/` | search | Home page - search box and index stat strip |
| GET | `/search?q=...&page=N&tab=X` | search | BM25 results page |
| GET | `/api/semantic?q=...` | api | HTMX fragment - AI summary + vector hits (async) |
| GET | `/history` | search | Search history for the logged-in user |
| POST | `/history/clear` | search | Delete all history rows for the current user |
| GET | `/history/_filter?q=...` | search | HTMX partial - filtered history list |
| GET/POST | `/settings` | search | User settings (theme, password change) |
| GET | `/login` | auth | Login page |
| GET/POST | `/register` | auth | Registration page |
| GET | `/api/search?q=...` | api | JSON search endpoint (CLI, scripts) |
| GET | `/api/stats` | api | JSON index statistics |

---

## Template Structure

```
flask_app/templates/
├── base.html              Master layout - theme, fonts, flash messages, blocks
├── _icons.html            Jinja macros for all SVG icons and the SHSE logo
├── _macros.html           Reusable form widgets (toggle switch, empty state)
├── _search.html           Search box partial (sm/md/lg sizes)
├── _topbar.html           Sticky header with logo and hamburger menu
├── _hamburger.html        Avatar popover with nav links and theme toggle
├── _result_item.html      Single BM25 result card (used inside results loop)
├── _semantic_rail.html    HTMX fragment - AI summary + semantic hits
├── home.html              Landing page with large search box and stat strip
├── results.html           Two-column results page (BM25 + async semantic rail)
├── history.html           Search history list with live filter
├── login.html             Login form (plain HTML, no WTForms)
├── register.html          Registration form; shows admin copy for first user
└── settings.html          User settings - theme, password change, clear history
```

---

## Settings Page

`GET/POST /settings` renders three sections:

| Section | Fields |
|---|---|
| Appearance | Theme (light / dark radio buttons) |
| Account | Username (read-only), Role (read-only), Change password form |
| Danger zone | Clear search history button |

Theme is stored in `session['theme']` and applied via the `data-theme` attribute on `<html>`. Password change requires the current password; the new password must be at least 8 characters.

> AI summary configuration is not yet user-configurable. It will be added as an admin-controlled setting in a future release (see Epic 18 in TODO.md).

## Semantic Rail

When `LLM_API_BASE` is configured, after BM25 results render the page fires `GET /api/semantic?q=...` via HTMX. The returned `<aside>` fragment can include:

| Section | Status |
|---|---|
| Suggested keywords | Functional - extracted from vector hit titles |
| AI summary | Not yet implemented - requires Epic 18 |
| Semantic matches | Functional - top-k vector search hits |

The rail loads asynchronously and never blocks BM25 results. If the LLM API is unreachable the rail is empty.

---

## Search History

`SearchHistory` rows are written after every successful authenticated search:

- Route: `_save_history(query)` in `flask_app/routes/search.py`
- Table: `search_history` (user_id FK → users.id, query, timestamp)
- Unauthenticated searches do not write history

The history page (`/history`) reads the current user's rows newest-first
and supports a live filter via `GET /history/_filter?q=...` (HTMX).

---

## Registration and Login

Neither form uses WTForms - plain HTML `<input>` elements POST to the auth routes.

`GET /register` passes `is_first` from the route; because a default admin account
is always created on first boot, `is_first` is effectively always `False` when
a user visits this page in practice. The "First-run setup" copy in the template
is dead code under normal operation.

`GET /login` passes `sso_enabled` from `Config.SSO_ENABLED`; when true, a
"Continue with SSO" button is rendered above the local login form.
