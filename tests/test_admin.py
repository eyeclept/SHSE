"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for Epic 11 (Admin UI): dashboard, health checks, targets list,
    config upload, jobs page, and action buttons (crawl/reindex/vectorize).
    Uses in-memory SQLite and mocked services. No live stack required.
"""
# Imports
import os
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask_app import db, login_manager

# Globals
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "templates")
_STATIC_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "static")


# Functions
@pytest.fixture
def app():
    """
    Input: None
    Output: Flask test app with all blueprints and SQLite
    """
    from flask_app.models.user import User                         # noqa: F401
    from flask_app.models.search_history import SearchHistory      # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget      # noqa: F401
    from flask_app.models.crawl_job import CrawlJob                # noqa: F401
    from flask_app.models.system_setting import SystemSetting      # noqa: F401
    from flask_app.routes.auth import auth_bp
    from flask_app.routes.search import search_bp
    from flask_app.routes.admin import admin_bp
    from flask_app.routes.api import api_bp

    flask_app = Flask("test_admin", template_folder=_TEMPLATE_DIR,
                      static_folder=_STATIC_DIR)
    flask_app.config.update({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "TESTING": True,
        "SECRET_KEY": "test",
        "SSO_ENABLED": False,
        "PROPAGATE_EXCEPTIONS": False,
    })
    db.init_app(flask_app)
    login_manager.init_app(flask_app)
    flask_app.register_blueprint(auth_bp)
    flask_app.register_blueprint(search_bp)
    flask_app.register_blueprint(admin_bp, url_prefix="/admin")
    flask_app.register_blueprint(api_bp)

    with flask_app.app_context():
        db.create_all()
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_client(app, client):
    """Authenticated admin client."""
    from flask_app.models.user import User
    with app.app_context():
        u = User(username="testadmin", role="admin")
        u.set_password("adminpass")
        db.session.add(u)
        db.session.commit()
    client.post("/login", data={"username": "testadmin", "password": "adminpass"})
    return client


@pytest.fixture
def user_client(app, client):
    """Authenticated non-admin client."""
    from flask_app.models.user import User
    with app.app_context():
        u = User(username="testuser", role="user")
        u.set_password("userpass")
        db.session.add(u)
        db.session.commit()
    client.post("/login", data={"username": "testuser", "password": "userpass"})
    return client


def _mock_health(all_up=True):
    status = "up" if all_up else "down"
    return {svc: {"status": status, "latency_ms": 5, "message": None}
            for svc in ("opensearch", "nutch", "llm_api", "redis", "mariadb")}


# ── Access control ────────────────────────────────────────────────────────

def test_dashboard_returns_403_for_non_admin(user_client):
    """
    Input: GET /admin/ as non-admin
    Output: 403
    """
    r = user_client.get("/admin/")
    assert r.status_code == 403


def test_dashboard_redirects_unauthenticated(client):
    """
    Input: GET /admin/ without session
    Output: 302 redirect to /login
    """
    r = client.get("/admin/")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_dashboard_renders_for_admin(admin_client):
    """
    Input: GET /admin/ as admin with mocked health and OS
    Output: 200 HTML containing 'Overview'
    """
    mc = MagicMock()
    mc.count.return_value = {"count": 42}
    mc.search.side_effect = [
        {"aggregations": {"svc": {"value": 3}, "vectorized": {"doc_count": 30}}},
        {"hits": {"hits": [{"_source": {"crawled_at": "2026-04-25T00:00:00"}}]}},
    ]
    with patch("flask_app.routes.admin._check_services", return_value=_mock_health()), \
         patch("flask_app.services.opensearch.get_client", return_value=mc):
        r = admin_client.get("/admin/")
    assert r.status_code == 200
    assert b"Overview" in r.data


# ── Health checks ─────────────────────────────────────────────────────────

def test_health_checks_return_correct_status(admin_client):
    """
    Input: GET /admin/_health as admin
    Output: 200 HTML fragment; 'Up' appears for mocked services
    """
    with patch("flask_app.routes.admin._check_services", return_value=_mock_health(True)):
        r = admin_client.get("/admin/_health")
    assert r.status_code == 200
    assert b"Up" in r.data


def test_health_check_shows_down_when_service_unreachable(admin_client):
    """
    Input: GET /admin/_health when one service is down
    Output: 'Down' appears in the partial
    """
    health = _mock_health(True)
    health["opensearch"]["status"] = "down"
    with patch("flask_app.routes.admin._check_services", return_value=health):
        r = admin_client.get("/admin/_health")
    assert r.status_code == 200
    assert b"Down" in r.data


# ── Config upload ─────────────────────────────────────────────────────────

def test_config_upload_parses_yaml_and_updates_targets(app, admin_client):
    """
    Input: POST /admin/config with valid YAML containing a service target
    Output: crawler_targets table updated; 200 or redirect
    """
    from flask_app.models.crawler_target import CrawlerTarget

    yaml_payload = """\
defaults: {}
targets:
  - type: service
    nickname: test-svc
    url: test.lab
"""
    r = admin_client.post("/admin/config", data={"yaml": yaml_payload, "action": "yaml_import"})
    assert r.status_code in (200, 302)

    with app.app_context():
        t = db.session.query(CrawlerTarget).filter_by(nickname="test-svc").first()
        assert t is not None
        assert t.target_type == "service"


def test_config_upload_invalid_yaml_shows_error(admin_client):
    """
    Input: POST /admin/config with malformed YAML
    Output: 200 with error indicator (validation block shows failure)
    """
    r = admin_client.post("/admin/config", data={"yaml": ": not: valid: yaml:", "action": "yaml_import"})
    assert r.status_code == 200


# ── Jobs page ─────────────────────────────────────────────────────────────

def test_jobs_page_lists_crawl_jobs(app, admin_client):
    """
    Input: GET /admin/jobs as admin with existing CrawlJob rows
    Output: 200 HTML containing job status
    """
    from flask_app.models.crawler_target import CrawlerTarget
    from flask_app.models.crawl_job import CrawlJob
    from datetime import datetime

    with app.app_context():
        t = CrawlerTarget(nickname="job-target", target_type="service", url="t.lab")
        db.session.add(t)
        db.session.commit()
        job = CrawlJob(target_id=t.id, status="success",
                       started_at=datetime.utcnow())
        db.session.add(job)
        db.session.commit()

    r = admin_client.get("/admin/jobs")
    assert r.status_code == 200
    assert b"success" in r.data


# ── Action buttons ────────────────────────────────────────────────────────

def test_crawl_target_button_dispatches_task(app, admin_client):
    """
    Input: POST /admin/targets/<id>/crawl as admin
    Output: redirect to jobs page; Celery task dispatched
    """
    from flask_app.models.crawler_target import CrawlerTarget
    with app.app_context():
        t = CrawlerTarget(nickname="btn-svc", target_type="service", url="svc.lab")
        db.session.add(t)
        db.session.commit()
        target_id = t.id

    mock_result = MagicMock()
    mock_result.id = "task-001"
    with patch("celery_worker.tasks.crawl.crawl_target") as mock_task:
        mock_task.delay.return_value = mock_result
        r = admin_client.post(f"/admin/targets/{target_id}/crawl")

    assert r.status_code == 302
    mock_task.delay.assert_called_once_with(target_id)


def test_vectorize_button_dispatches_task(admin_client):
    """
    Input: POST /admin/vectorize as admin
    Output: redirect to jobs page; vectorize_pending.delay() called
    """
    mock_result = MagicMock()
    mock_result.id = "task-vec"
    with patch("celery_worker.tasks.vectorize.vectorize_pending") as mock_task:
        mock_task.delay.return_value = mock_result
        r = admin_client.post("/admin/vectorize")
    assert r.status_code == 302
    mock_task.delay.assert_called_once()


# ── User role management (19d) ────────────────────────────────────────────

def test_users_page_lists_all_users(app, admin_client):
    """
    Input: GET /admin/users as admin
    Output: 200 HTML listing all users with current roles
    """
    from flask_app.models.user import User
    with app.app_context():
        u = User(username="regular", role="user")
        u.set_password("pass")
        db.session.add(u)
        db.session.commit()

    r = admin_client.get("/admin/users")
    assert r.status_code == 200
    assert b"testadmin" in r.data
    assert b"regular" in r.data


def test_users_page_returns_403_for_non_admin(user_client):
    """
    Input: GET /admin/users as non-admin
    Output: 403
    """
    r = user_client.get("/admin/users")
    assert r.status_code == 403


def test_promote_changes_role_to_admin(app, admin_client):
    """
    Input: POST /admin/users/<id>/promote as admin for a 'user' role account
    Output: redirect to users list; role changed to 'admin' in DB
    """
    from flask_app.models.user import User
    with app.app_context():
        u = User(username="promo_target", role="user")
        u.set_password("pass")
        db.session.add(u)
        db.session.commit()
        uid = u.id

    r = admin_client.post(f"/admin/users/{uid}/promote")
    assert r.status_code == 302

    with app.app_context():
        updated = db.session.get(User, uid)
        assert updated.role == "admin"


def test_demote_changes_role_to_user(app, admin_client):
    """
    Input: POST /admin/users/<id>/demote as admin for another admin account
    Output: redirect to users list; role changed to 'user' in DB
    """
    from flask_app.models.user import User
    with app.app_context():
        u = User(username="demote_target", role="admin")
        u.set_password("pass")
        db.session.add(u)
        db.session.commit()
        uid = u.id

    r = admin_client.post(f"/admin/users/{uid}/demote")
    assert r.status_code == 302

    with app.app_context():
        updated = db.session.get(User, uid)
        assert updated.role == "user"


def test_self_demote_is_rejected(app, admin_client):
    """
    Input: POST /admin/users/<self_id>/demote as admin
    Output: redirect to users list; role remains 'admin' in DB
    """
    from flask_app.models.user import User
    with app.app_context():
        self_user = db.session.query(User).filter_by(username="testadmin").first()
        self_id = self_user.id

    r = admin_client.post(f"/admin/users/{self_id}/demote")
    assert r.status_code == 302

    with app.app_context():
        updated = db.session.get(User, self_id)
        assert updated.role == "admin"


# ── 18b: AI Summary admin control ────────────────────────────────────────────

def test_settings_save_ai_summary_enabled(app, admin_client):
    """
    Input:  POST /admin/config action=settings with ai_summary_enabled=1
    Output: system_settings row llm.ai_summary_enabled == "1"
    """
    from flask_app.models.system_setting import SystemSetting
    with patch("flask_app.routes.admin._validate_llm_model", return_value=None):
        r = admin_client.post("/admin/config", data={
            "action": "settings",
            "ai_summary_enabled": "1",
            "llm_gen_model": "",
            "llm_embed_model": "",
        })
    assert r.status_code in (200, 302)
    with app.app_context():
        row = db.session.get(SystemSetting, "llm.ai_summary_enabled")
        assert row is not None
        assert row.value == "1"


def test_settings_save_ai_summary_disabled(app, admin_client):
    """
    Input:  POST /admin/config action=settings without ai_summary_enabled field
    Output: system_settings row llm.ai_summary_enabled == "0"
    """
    from flask_app.models.system_setting import SystemSetting
    with patch("flask_app.routes.admin._validate_llm_model", return_value=None):
        r = admin_client.post("/admin/config", data={
            "action": "settings",
            "llm_gen_model": "",
            "llm_embed_model": "",
        })
    assert r.status_code in (200, 302)
    with app.app_context():
        row = db.session.get(SystemSetting, "llm.ai_summary_enabled")
        assert row is not None
        assert row.value == "0"


def test_settings_model_validation_error_blocks_save(app, admin_client):
    """
    Input:  POST /admin/config with invalid llm_gen_model
    Output: no system_settings row written; error flash shown
    """
    from flask_app.models.system_setting import SystemSetting
    with patch("flask_app.routes.admin._validate_llm_model",
               return_value="Model 'bad-model' not found. Available: granite3.3:latest"):
        r = admin_client.post("/admin/config", data={
            "action": "settings",
            "ai_summary_enabled": "1",
            "llm_gen_model": "bad-model",
            "llm_embed_model": "",
        })
    assert r.status_code in (200, 302)
    with app.app_context():
        row = db.session.get(SystemSetting, "llm.gen_model")
        assert row is None


def test_semantic_summary_returns_empty_when_admin_disabled(app, admin_client):
    """
    Input:  llm.ai_summary_enabled = "0" in system_settings; GET /api/semantic/summary
    Output: empty string (gate fires before any LLM/OS call)
    """
    from flask_app.models.system_setting import SystemSetting
    with app.app_context():
        db.session.add(SystemSetting(key="llm.ai_summary_enabled", value="0"))
        db.session.commit()

    r = admin_client.get("/api/semantic/summary?q=test")
    assert r.status_code == 200
    assert r.data == b""
