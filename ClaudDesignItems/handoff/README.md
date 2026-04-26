# Claude Code port kit — SHSE

A **runnable Flask skeleton** + Jinja templates for every SHSE screen,
ready for Claude Code to wire up to OpenSearch, Celery, MariaDB, and
Authentik. Every template renders today against the JSON fixtures in
`fixtures/`; you swap fixtures for live data sprint by sprint.

## What's here

```
handoff/
├── app.py                          Flask skeleton. Routes for every
│                                   screen + every HTMX partial endpoint.
│                                   All non-home routes abort(501) with
│                                   TODO pointers to the prototype.
├── _gallery.html                   Static design-system gallery — open
│                                   in a browser to eyeball every
│                                   primitive in tokens.css.
├── static/
│   └── css/
│       └── tokens.css              All CSS custom properties + primitive
│                                   classes (.shse-btn, .shse-pill,
│                                   .shse-tab, .shse-card, etc.)
│                                   ported verbatim from src/theme.jsx.
├── fixtures/                       JSON snapshots of the data each
│                                   route renders with. Drop into
│                                   render_template(...) to see any
│                                   template against real-shaped data.
│                                   See fixtures/README.md.
└── templates/
    ├── base.html                   <html data-theme>, fonts, tokens.css,
    │                               flash messages, skip link, blocks.
    ├── _icons.html                 Jinja macros for every icon + glyph + logo.
    ├── _macros.html                Reusable widgets: toggle, empty_state,
    │                               skeleton_row, spinner, error_block.
    ├── _topbar.html                Sticky header with logo + hamburger.
    ├── _hamburger.html             Account / theme / nav menu.
    ├── _search.html                Search input partial (size sm/md/lg).
    ├── _result_item.html           One BM25 result card.
    ├── home.html                   Startpage layout.
    ├── search.html                 Two-column results (BM25 + semantic rail).
    ├── login.html                  Sign in (+ optional Authentik SSO).
    ├── register.html               Open registration / first-run setup.
    ├── settings.html               Per-user prefs (incl. AI summary toggle,
    │                               summary_model select). The two fields
    │                               in the Claude Code checklist are tagged.
    ├── history.html                Search history with HTMX live filter.
    └── admin/
        ├── _subnav.html            Admin tab strip.
        ├── _health_grid.html       Service health tiles (HTMX-pollable).
        ├── _jobs_rows.html         <tbody> for jobs table (HTMX swap target).
        ├── _yaml_validation.html   Live YAML validation panel.
        ├── index.html              Overview / dashboard + recent activity.
        ├── targets.html            Crawler target list with per-row
        │                           crawl/reindex/vectorize buttons that
        │                           auto-disable on service-down.
        ├── jobs.html               Crawl jobs list (polls every 2s).
        ├── config.html             YAML editor with debounced live validation.
        └── index_ops.html          Cross-target reindex/vectorize +
                                    drop-and-recreate (with confirm).
```

## How to run

```
pip install flask
cd handoff
FLASK_APP=app.py flask run
```

Open <http://127.0.0.1:5000/> — the home page works end-to-end.
Every other route 501s with a comment pointing at the prototype source
and the corresponding template.

To preview a screen without writing the route, wire it through a
fixture (see `fixtures/README.md` for a one-paragraph recipe).

## Mapping to the Claude Code checklist

The kit covers Epics 10 (Search UI) and 11 (Admin UI). Filenames match
the checklist exactly:

| Checklist | File |
|---|---|
| Epic 10 / Step 1 | `templates/base.html` |
| Epic 10 / Step 2 | `templates/search.html` + `_result_item.html` |
| Epic 10 / Step 4 | AI summary `<details>` block in `search.html` |
| Epic 10 / Step 6 | `templates/login.html` |
| Epic 10 / Step 7 | `templates/register.html` |
| Epic 10 / Step 8 | `templates/settings.html` |
| Epic 10 / Step 10 | `templates/history.html` |
| Epic 11 / Step 1 | `templates/admin/index.html` |
| Epic 11 / Step 2 | `_health_grid.html` (HTMX target) + `/admin/_health` route |
| Epic 11 / Step 3 | `templates/admin/targets.html` |
| Epic 11 / Step 4 | `templates/admin/config.html` + `_yaml_validation.html` |
| Epic 11 / Step 6 | `templates/admin/jobs.html` + `_jobs_rows.html` |
| Epic 11 / Step 8 | Service-down disabling baked into `targets.html` |

## The porting pattern

For each route in `app.py`:

1. **Read the route's docstring.** It points to the prototype source
   (`src/screens/*.jsx`) and the corresponding template.
2. **Replace `abort(501)`** with the real query layer. The route
   already declares the context shape via the `_fixture(...)` helper
   pattern in `fixtures/README.md`.
3. **Pass the same keys** the template expects — every template's
   header comment lists exactly what its context dict needs.
4. **Add Flask-Login `@login_required`** (and `current_user.role == 'admin'`
   gating for `/admin/*`) where noted in the docstrings.

## Out-of-spec extras

These are wider than the literal checklist — keep or drop per Sprint
priorities:

- `register.html` doubles as first-run setup (first user → admin).
- `settings.html` includes per-page count, save-history toggle, theme.
  The checklist only requires AI summary + summary_model; both are
  the first two rows of the Search section.
- `admin/index_ops.html` exposes drop-and-recreate as a destructive
  action. Not required by Epic 11 but you'll want it during dev.

## See also

- `fixtures/README.md` — JSON snapshot contracts.
- `_gallery.html` — visual reference for tokens.css.
- `HANDOFF.md` (project root) — high-level architecture + sprint plan.
