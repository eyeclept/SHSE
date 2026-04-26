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


@app.route("/register", methods=["GET", "POST"])
def register():
    """Open registration. First user becomes role='admin' (is_first=True
    is computed in the handler from User.query.count() == 0).
    TODO Sprint 1 — see src/screens/auth.jsx."""
    abort(501)


@app.route("/sso/start")
def sso_start():
    """Authentik OIDC kickoff (Authlib). TODO Sprint 1 if SSO_ENABLED."""
    abort(501)


@app.route("/history/_filter")
def history_filter():
    """HTMX partial — returns just <ul#history-list> filtered by ?q=
    TODO Sprint 4."""
    abort(501)


@app.route("/history/clear", methods=["POST"])
def clear_history():
    """TODO Sprint 4 — DELETE FROM search_history WHERE user_id=current_user.id."""
    abort(501)


@app.route("/settings/password", methods=["GET", "POST"])
def password_modal():
    """HTMX partial; returns the change-password modal markup. TODO Sprint 4."""
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
    """TODO Sprint 5 — admin.jsx <AdminOverview>. Renders templates/admin/index.html."""
    abort(501)


@app.route("/admin/_health")
def admin_health_partial():
    """HTMX poll target. Returns templates/admin/_health_grid.html only.
    hx-trigger='every 5s' on the parent div. TODO Sprint 5."""
    abort(501)


@app.route("/admin/targets")
def admin_targets():
    """TODO Sprint 5 — admin.jsx <AdminTargets>. templates/admin/targets.html."""
    abort(501)


@app.route("/admin/targets/<int:target_id>/crawl", methods=["POST"])
def admin_target_crawl(target_id):
    """Enqueue Celery crawl task. TODO Sprint 5."""
    abort(501)


@app.route("/admin/targets/<int:target_id>/reindex", methods=["POST"])
def admin_target_reindex(target_id):
    """Enqueue Celery reindex task. TODO Sprint 5."""
    abort(501)


@app.route("/admin/targets/<int:target_id>/vectorize", methods=["POST"])
def admin_target_vectorize(target_id):
    """Enqueue Celery vectorize task. TODO Sprint 5."""
    abort(501)


@app.route("/admin/jobs")
def admin_jobs():
    """TODO Sprint 6 — admin.jsx <AdminJobs>. HTMX-poll every 2s."""
    abort(501)


@app.route("/admin/jobs/_table")
def admin_jobs_table():
    """HTMX partial — returns templates/admin/_jobs_rows.html (just <tbody>).
    TODO Sprint 6."""
    abort(501)


@app.route("/admin/jobs/<int:job_id>")
def admin_job_detail(job_id):
    """Per-job logs / stack trace. TODO Sprint 6."""
    abort(501)


@app.route("/admin/jobs/<int:job_id>/cancel", methods=["POST"])
def admin_job_cancel(job_id):
    """Revoke Celery task. TODO Sprint 6."""
    abort(501)


@app.route("/admin/config", methods=["GET", "POST"])
def admin_config():
    """TODO Sprint 6 — admin.jsx <AdminConfig>. YAML editor."""
    abort(501)


@app.route("/admin/config/_validate", methods=["POST"])
def admin_config_validate():
    """HTMX partial — returns templates/admin/_yaml_validation.html.
    Debounced input handler from the editor textarea. TODO Sprint 6."""
    abort(501)


@app.route("/admin/index")
def admin_index_ops():
    """TODO Sprint 6 — admin.jsx <AdminIndex>. templates/admin/index_ops.html."""
    abort(501)


@app.route("/admin/index/reindex_all", methods=["POST"])
def admin_reindex_all():
    """Full-corpus reindex. TODO Sprint 6."""
    abort(501)


@app.route("/admin/index/vectorize_all", methods=["POST"])
def admin_vectorize_all():
    """Full-corpus vectorize. TODO Sprint 6."""
    abort(501)


@app.route("/admin/index/drop", methods=["POST"])
def admin_drop_index():
    """Destructive: drop+recreate index. Requires confirm_text == 'DROP'.
    TODO Sprint 6."""
    abort(501)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
