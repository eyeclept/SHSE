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
| GET/POST | `/settings` | search | User settings (AI summary toggle) |
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
└── settings.html          User settings - AI summary toggle
```

---

## AI Summary Toggle

AI summary and vector search are enabled by default. The session key
`ai_summary_enabled` (default `True`) controls the preference:

- Set via `POST /settings` with `ai_summary_enabled=on` or omitted
- When `False`, the search route returns `show_bm25_warning=True` and the
  semantic rail is not requested

The semantic rail is always loaded asynchronously via HTMX regardless of the
toggle - the route just skips the LLM call and returns an empty aside.

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

`GET /register` passes `is_first=True` when the `users` table is empty; the
template shows "First-run setup" copy and notes that the account will have
admin access.

`GET /login` passes `sso_enabled` from `Config.SSO_ENABLED`; when true, an
SSO button appears above the local form.
