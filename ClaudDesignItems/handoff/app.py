"""
SHSE — minimal Flask skeleton.

This is the REFERENCE entry point for the Claude Code port. It shows
how the prototype's screen → template → route mapping works. Only the
home page is wired up; the rest of the routes are stubs that 404 with
a TODO pointer to the relevant prototype file.

Run:
    pip install flask
    FLASK_APP=app.py flask run

Production wiring (not in this skeleton):
    - Flask-Login (users + role-gate on /admin/*)
    - Authlib for optional Authentik OIDC when SSO_ENABLED=true
    - Celery client (dispatches crawl / reindex / vectorize tasks via Redis)
    - OpenSearch client (BM25 search, facets, highlight)
    - MariaDB (SQLAlchemy) for users / search_history / crawler_targets / crawl_jobs
"""
from __future__ import annotations

from flask import Flask, render_template, request, redirect, url_for, abort

app = Flask(__name__)
app.secret_key = "dev-only-change-me"  # TODO Sprint 1: load from env


# ── Mock data. Replace with real queries during implementation. ──────
def get_index_stats() -> dict:
    """Cached stats shown on home + admin overview.
    Prod: SELECT COUNT(*) FROM opensearch index, COUNT DISTINCT service_nickname,
          MAX(crawled_at) → humanize. Cache 60s in Redis."""
    return {
        "docs": 1_402_198,
        "services": 6,
        "last_crawl": "5h ago",
    }


# ── Routes ───────────────────────────────────────────────────────────

@app.route("/")
def home():
    """Home page. See prototype: src/screens/home.jsx (Startpage layout)."""
    return render_template("home.html", stats=get_index_stats())


@app.route("/search")
def search():
    """Results. See prototype: src/screens/results.jsx (Classic layout).
    TODO Sprint 3:
      - q = request.args.get("q", "").strip()
      - OpenSearch BM25 + `highlight` on `text` field
      - facet aggregation on `service_nickname` for right-rail
      - if user.settings.ai_summary: embed q, vector search, RAG via LLM_API
    """
    abort(501, "TODO Sprint 3 — see src/screens/results.jsx")


@app.route("/login", methods=["GET", "POST"])
def login():
    """TODO Sprint 1 — see src/screens/auth.jsx (mode='login')."""
    abort(501)


@app.route("/setup", methods=["GET", "POST"])
def setup():
    """First-run admin creation. TODO Sprint 1 — auth.jsx (mode='setup')."""
    abort(501)


@app.route("/history")
def history():
    """TODO Sprint 4 — settings.jsx <ShseHistory>."""
    abort(501)


@app.route("/settings", methods=["GET", "POST"])
def settings():
    """TODO Sprint 4 — settings.jsx <ShseSettings>."""
    abort(501)


# ── Admin (role=admin only). Sprints 5-6. ────────────────────────────

@app.route("/admin")
def admin_overview():
    """TODO Sprint 5 — admin.jsx <AdminOverview>."""
    abort(501)


@app.route("/admin/targets")
def admin_targets():
    """TODO Sprint 5 — admin.jsx <AdminTargets>."""
    abort(501)


@app.route("/admin/jobs")
def admin_jobs():
    """TODO Sprint 6 — admin.jsx <AdminJobs>. HTMX-poll every 2s."""
    abort(501)


@app.route("/admin/config", methods=["GET", "POST"])
def admin_config():
    """TODO Sprint 6 — admin.jsx <AdminConfig>. YAML editor."""
    abort(501)


@app.route("/admin/index")
def admin_index_ops():
    """TODO Sprint 6 — admin.jsx <AdminIndex>. Vectorize + reindex."""
    abort(501)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
