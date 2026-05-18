"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for cli.py. Each command function is tested directly (not via subprocess)
    to validate output, exit codes, and downstream calls without requiring a running
    Docker stack. DB-backed commands use an in-memory SQLite fixture. Network calls
    (OpenSearch, Redis, Flask API, MariaDB admin) are mocked.
"""
# Imports
import os
import sys
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest
from flask import Flask
from flask_app import db, login_manager

# Globals
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "templates")
_STATIC_DIR   = os.path.join(_PROJECT_ROOT, "flask_app", "static")


# Functions
@pytest.fixture
def cli_app():
    """
    Input: None
    Output: (Flask app, db) tuple with in-memory SQLite
    Details:
        Minimal Flask app for commands that need a DB context.
        Imports all models before create_all so all tables are created.
    """
    from flask_app.models.user import User                                    # noqa: F401
    from flask_app.models.search_history import SearchHistory                 # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget                 # noqa: F401
    from flask_app.models.crawl_job import CrawlJob                           # noqa: F401
    from flask_app.models.password_reset_token import PasswordResetToken      # noqa: F401
    from flask_app.models.webauthn_credential import WebAuthnCredential       # noqa: F401
    from flask_app.models.system_setting import SystemSetting                 # noqa: F401

    app = Flask("test_cli", template_folder=_TEMPLATE_DIR, static_folder=_STATIC_DIR)
    app.config.update({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "TESTING": True,
        "SECRET_KEY": "test",
    })
    db.init_app(app)
    login_manager.init_app(app)

    with app.app_context():
        db.create_all()
        yield app, db
        db.drop_all()


def _args(**kwargs):
    """Build a SimpleNamespace to simulate parsed argparse arguments."""
    return SimpleNamespace(**kwargs)


# ── stats ──────────────────────────────────────────────────────────────────


def test_cmd_stats_prints_counts(capsys):
    """
    Input: mocked OpenSearch client
    Output: stats printed to stdout
    """
    from cli import cmd_stats

    mock_client = MagicMock()
    mock_client.count.return_value = {"count": 42}
    mock_client.search.side_effect = [
        {"aggregations": {"svc": {"value": 3}}},
        {"hits": {"hits": [{"_source": {"crawled_at": "2026-05-01T10:00:00"}}]}},
    ]

    with patch("cli._load_env"), \
         patch("flask_app.services.opensearch.get_client", return_value=mock_client):
        cmd_stats(_args())

    out = capsys.readouterr().out
    assert "42" in out
    assert "3" in out
    assert "2026-05-01" in out


def test_cmd_stats_exits_on_opensearch_error(capsys):
    """
    Input: OpenSearch raises exception
    Output: error printed; sys.exit(1) raised
    """
    from cli import cmd_stats

    with patch("cli._load_env"), \
         patch("flask_app.services.opensearch.get_client", side_effect=Exception("conn refused")):
        with pytest.raises(SystemExit) as exc:
            cmd_stats(_args())
    assert exc.value.code == 1
    assert "error" in capsys.readouterr().err


# ── list-targets ───────────────────────────────────────────────────────────


def test_cmd_list_targets_empty(capsys, cli_app):
    """
    Input: no targets in DB
    Output: "no targets configured"
    """
    from cli import cmd_list_targets
    app, _ = cli_app

    with patch("cli._load_env"), \
         patch("cli._get_app", return_value=(app, db)):
        cmd_list_targets(_args())

    assert "no targets" in capsys.readouterr().out


def test_cmd_list_targets_shows_targets(capsys, cli_app):
    """
    Input: two targets in DB
    Output: both nicknames printed
    """
    from cli import cmd_list_targets
    from flask_app.models.crawler_target import CrawlerTarget
    app, _ = cli_app

    with app.app_context():
        db.session.add(CrawlerTarget(nickname="blog", target_type="service", url="blog.lab"))
        db.session.add(CrawlerTarget(nickname="wiki", target_type="service", url="wiki.lab"))
        db.session.commit()

    with patch("cli._load_env"), \
         patch("cli._get_app", return_value=(app, db)):
        cmd_list_targets(_args())

    out = capsys.readouterr().out
    assert "blog" in out
    assert "wiki" in out


# ── upload-config ──────────────────────────────────────────────────────────


def test_cmd_upload_config_missing_file(capsys, tmp_path):
    """
    Input: non-existent file path
    Output: error message; sys.exit(1)
    """
    from cli import cmd_upload_config

    with patch("cli._load_env"):
        with pytest.raises(SystemExit) as exc:
            cmd_upload_config(_args(file=str(tmp_path / "nope.yaml")))
    assert exc.value.code == 1
    assert "not found" in capsys.readouterr().err


def test_cmd_upload_config_success(capsys, tmp_path, cli_app):
    """
    Input: valid YAML file
    Output: count of persisted targets printed
    """
    from cli import cmd_upload_config
    from flask_app.models.crawler_target import CrawlerTarget
    app, _ = cli_app

    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("targets:\n  - type: service\n    nickname: test\n    url: test.lab\n")

    mock_target = MagicMock()
    mock_target.id = 1
    mock_target.target_type = "service"
    mock_target.nickname = "test"
    mock_target.network = None

    with patch("cli._load_env"), \
         patch("cli._get_app", return_value=(app, db)), \
         patch("flask_app.config_parser.parse_config", return_value=[mock_target]), \
         patch("flask_app.config_parser.persist_targets", return_value=[mock_target]):
        cmd_upload_config(_args(file=str(yaml_file)))

    assert "1 target" in capsys.readouterr().out


# ── crawl ──────────────────────────────────────────────────────────────────


def test_cmd_crawl_dispatches_task(capsys, cli_app):
    """
    Input: valid nickname
    Output: task ID printed
    """
    from cli import cmd_crawl
    from flask_app.models.crawler_target import CrawlerTarget
    app, _ = cli_app

    with app.app_context():
        db.session.add(CrawlerTarget(nickname="blog", target_type="service", url="blog.lab"))
        db.session.commit()

    mock_result = MagicMock()
    mock_result.id = "task-abc"

    with patch("cli._load_env"), \
         patch("cli._get_app", return_value=(app, db)), \
         patch("celery_worker.tasks.crawl.crawl_target") as mock_task:
        mock_task.delay.return_value = mock_result
        cmd_crawl(_args(nickname="blog"))

    out = capsys.readouterr().out
    assert "task-abc" in out
    mock_task.delay.assert_called_once()


def test_cmd_crawl_unknown_nickname_exits(capsys, cli_app):
    """
    Input: nickname not in DB
    Output: error; sys.exit(1)
    """
    from cli import cmd_crawl
    app, _ = cli_app

    with patch("cli._load_env"), \
         patch("cli._get_app", return_value=(app, db)):
        with pytest.raises(SystemExit) as exc:
            cmd_crawl(_args(nickname="nope"))
    assert exc.value.code == 1


# ── crawl-all ──────────────────────────────────────────────────────────────


def test_cmd_crawl_all_dispatches(capsys):
    """
    Input: none
    Output: task ID printed
    """
    from cli import cmd_crawl_all

    mock_result = MagicMock()
    mock_result.id = "task-xyz"

    with patch("cli._load_env"), \
         patch("celery_worker.tasks.crawl.crawl_all") as mock_task:
        mock_task.delay.return_value = mock_result
        cmd_crawl_all(_args())

    assert "task-xyz" in capsys.readouterr().out
    mock_task.delay.assert_called_once()


# ── reindex ────────────────────────────────────────────────────────────────


def test_cmd_reindex_dispatches(capsys, cli_app):
    """
    Input: valid nickname
    Output: task ID printed
    """
    from cli import cmd_reindex
    from flask_app.models.crawler_target import CrawlerTarget
    app, _ = cli_app

    with app.app_context():
        db.session.add(CrawlerTarget(nickname="wiki", target_type="service", url="wiki.lab"))
        db.session.commit()

    mock_result = MagicMock()
    mock_result.id = "task-re1"

    with patch("cli._load_env"), \
         patch("cli._get_app", return_value=(app, db)), \
         patch("celery_worker.tasks.index.reindex_target") as mock_task:
        mock_task.delay.return_value = mock_result
        cmd_reindex(_args(nickname="wiki"))

    assert "task-re1" in capsys.readouterr().out


# ── reindex-all ────────────────────────────────────────────────────────────


def test_cmd_reindex_all_with_yes_flag(capsys):
    """
    Input: --yes flag
    Output: dispatched; no prompt
    """
    from cli import cmd_reindex_all

    mock_result = MagicMock()
    mock_result.id = "task-ra1"

    with patch("cli._load_env"), \
         patch("celery_worker.tasks.index.reindex_all") as mock_task:
        mock_task.delay.return_value = mock_result
        cmd_reindex_all(_args(yes=True))

    assert "task-ra1" in capsys.readouterr().out


def test_cmd_reindex_all_aborts_on_n(capsys, monkeypatch):
    """
    Input: user types 'n' at confirmation
    Output: "aborted" printed; no task dispatched
    """
    from cli import cmd_reindex_all

    monkeypatch.setattr("builtins.input", lambda _: "n")

    with patch("cli._load_env"), \
         patch("celery_worker.tasks.index.reindex_all") as mock_task:
        cmd_reindex_all(_args(yes=False))

    assert "aborted" in capsys.readouterr().out
    mock_task.delay.assert_not_called()


def test_cmd_reindex_all_proceeds_on_y(capsys, monkeypatch):
    """
    Input: user types 'y' at confirmation
    Output: task dispatched
    """
    from cli import cmd_reindex_all

    monkeypatch.setattr("builtins.input", lambda _: "y")
    mock_result = MagicMock()
    mock_result.id = "task-ra2"

    with patch("cli._load_env"), \
         patch("celery_worker.tasks.index.reindex_all") as mock_task:
        mock_task.delay.return_value = mock_result
        cmd_reindex_all(_args(yes=False))

    assert "task-ra2" in capsys.readouterr().out


# ── vectorize ──────────────────────────────────────────────────────────────


def test_cmd_vectorize_dispatches(capsys):
    """
    Input: none
    Output: task ID printed
    """
    from cli import cmd_vectorize

    mock_result = MagicMock()
    mock_result.id = "task-vec1"

    with patch("cli._load_env"), \
         patch("celery_worker.tasks.vectorize.vectorize_pending") as mock_task:
        mock_task.delay.return_value = mock_result
        cmd_vectorize(_args())

    assert "task-vec1" in capsys.readouterr().out


# ── create-index ───────────────────────────────────────────────────────────


def test_cmd_create_index_new(capsys):
    """
    Input: index does not exist
    Output: "index created" printed
    """
    from cli import cmd_create_index

    with patch("cli._load_env"), \
         patch("flask_app.services.opensearch.create_index", return_value={"acknowledged": True}):
        cmd_create_index(_args())

    assert "index created" in capsys.readouterr().out


def test_cmd_create_index_already_exists(capsys):
    """
    Input: index already exists
    Output: "already exists" printed; no error
    """
    from cli import cmd_create_index

    with patch("cli._load_env"), \
         patch("flask_app.services.opensearch.create_index", return_value={"already_exists": True}):
        cmd_create_index(_args())

    assert "already exists" in capsys.readouterr().out


# ── wipe-index ─────────────────────────────────────────────────────────────


def test_cmd_wipe_index_with_yes_flag(capsys):
    """
    Input: --yes flag
    Output: deleted count printed; no prompt
    """
    from cli import cmd_wipe_index

    with patch("cli._load_env"), \
         patch("flask_app.services.opensearch.wipe_index", return_value={"deleted": 99}):
        cmd_wipe_index(_args(yes=True))

    assert "99" in capsys.readouterr().out


def test_cmd_wipe_index_aborts_on_n(capsys, monkeypatch):
    """
    Input: user types 'n' at confirmation
    Output: "aborted" printed; wipe_index not called
    """
    from cli import cmd_wipe_index

    monkeypatch.setattr("builtins.input", lambda _: "n")

    with patch("cli._load_env"), \
         patch("flask_app.services.opensearch.wipe_index") as mock_wipe:
        cmd_wipe_index(_args(yes=False))

    assert "aborted" in capsys.readouterr().out
    mock_wipe.assert_not_called()


# ── search ─────────────────────────────────────────────────────────────────


def test_cmd_search_prints_results(capsys):
    """
    Input: mock Flask API returning two results
    Output: titles and URLs printed
    """
    import json
    from cli import cmd_search

    payload = {
        "q": "nginx", "total": 2, "took_ms": 5, "page": 1, "page_count": 1,
        "results": [
            {"title": "Nginx Guide", "url": "http://docs.lab/nginx",
             "service": "docs", "snippet": "A web server.", "vectorized": True},
            {"title": "Nginx Config", "url": "http://docs.lab/nginx/config",
             "service": "docs", "snippet": "Config reference.", "vectorized": False},
        ],
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("cli._load_env"), \
         patch("urllib.request.urlopen", return_value=mock_resp):
        cmd_search(_args(query="nginx", page=1, limit=10))

    out = capsys.readouterr().out
    assert "Nginx Guide" in out
    assert "Nginx Config" in out
    assert "[BM25 only]" in out


def test_cmd_search_no_results(capsys):
    """
    Input: mock Flask API returning zero results
    Output: "no results" printed
    """
    import json
    from cli import cmd_search

    payload = {"q": "nope", "total": 0, "took_ms": 1, "page": 1, "page_count": 1, "results": []}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("cli._load_env"), \
         patch("urllib.request.urlopen", return_value=mock_resp):
        cmd_search(_args(query="nope", page=1, limit=10))

    assert "no results" in capsys.readouterr().out


def test_cmd_search_flask_unreachable_exits(capsys):
    """
    Input: Flask not reachable
    Output: error; sys.exit(1)
    """
    from cli import cmd_search

    with patch("cli._load_env"), \
         patch("urllib.request.urlopen", side_effect=Exception("connection refused")):
        with pytest.raises(SystemExit) as exc:
            cmd_search(_args(query="test", page=1, limit=10))

    assert exc.value.code == 1


# ── jobs ───────────────────────────────────────────────────────────────────


def test_cmd_jobs_empty(capsys, cli_app):
    """
    Input: no CrawlJob rows
    Output: "no jobs found"
    """
    from cli import cmd_jobs
    app, _ = cli_app

    with patch("cli._load_env"), \
         patch("cli._get_app", return_value=(app, db)):
        cmd_jobs(_args(limit=20))

    assert "no jobs" in capsys.readouterr().out


def test_cmd_jobs_shows_rows(capsys, cli_app):
    """
    Input: one CrawlJob row
    Output: job printed with status
    """
    from cli import cmd_jobs
    from flask_app.models.crawl_job import CrawlJob
    app, _ = cli_app

    with app.app_context():
        db.session.add(CrawlJob(kind="crawl", status="success", task_id="t123"))
        db.session.commit()

    with patch("cli._load_env"), \
         patch("cli._get_app", return_value=(app, db)):
        cmd_jobs(_args(limit=20))

    out = capsys.readouterr().out
    assert "success" in out
    assert "t123" in out


# ── reset-admin-password ───────────────────────────────────────────────────


def test_reset_admin_password_impl_valid(cli_app):
    """
    Input: valid admin username and new password
    Output: password updated; check_password succeeds with new password
    """
    from cli import _reset_admin_password_impl
    from flask_app.models.user import User
    app, _ = cli_app

    with app.app_context():
        u = User(username="testadmin", role="admin")
        u.set_password("oldpass123")
        db.session.add(u)
        db.session.commit()

        _reset_admin_password_impl(db.session, "testadmin", "newpass456")

        updated = db.session.query(User).filter_by(username="testadmin").first()
        assert updated.check_password("newpass456")
        assert not updated.check_password("oldpass123")


def test_reset_admin_password_impl_nonexistent_exits(capsys, cli_app):
    """
    Input: username not in DB
    Output: sys.exit(1)
    """
    from cli import _reset_admin_password_impl
    app, _ = cli_app

    with app.app_context():
        with pytest.raises(SystemExit) as exc:
            _reset_admin_password_impl(db.session, "nobody", "pass12345")
    assert exc.value.code == 1


def test_reset_admin_password_impl_non_admin_exits(capsys, cli_app):
    """
    Input: username is a regular user, not admin
    Output: sys.exit(1)
    """
    from cli import _reset_admin_password_impl
    from flask_app.models.user import User
    app, _ = cli_app

    with app.app_context():
        u = User(username="regularuser", role="user")
        u.set_password("pass12345")
        db.session.add(u)
        db.session.commit()

        with pytest.raises(SystemExit) as exc:
            _reset_admin_password_impl(db.session, "regularuser", "newpass456")
    assert exc.value.code == 1


# ── setup-db ───────────────────────────────────────────────────────────────


def test_cmd_setup_db_runs_ddl(capsys):
    """
    Input: mocked admin engine and verify engine
    Output: DDL statements executed; verification connection made
    """
    from cli import cmd_setup_db

    mock_conn = MagicMock()
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_conn
    mock_engine.dialect.identifier_preparer.quote = lambda x: f"`{x}`"

    mock_verify_conn = MagicMock()
    mock_verify_conn.__enter__ = lambda s: s
    mock_verify_conn.__exit__ = MagicMock(return_value=False)

    mock_verify_engine = MagicMock()
    mock_verify_engine.connect.return_value = mock_verify_conn

    engines = [mock_engine, mock_verify_engine]

    with patch("cli._load_env"), \
         patch("flask_app.config.Config.MARIADB_HOST", "dbhost"), \
         patch("flask_app.config.Config.MARIADB_PORT", "3306"), \
         patch("flask_app.config.Config.MARIADB_DB", "shse"), \
         patch("flask_app.config.Config.MARIADB_USER", "shse_user"), \
         patch("flask_app.config.Config.MARIADB_PASSWORD", "secret"), \
         patch("sqlalchemy.create_engine", side_effect=engines):
        cmd_setup_db(_args(admin_user="root", admin_password="rootpass"))

    out = capsys.readouterr().out
    assert "shse" in out
    assert "shse_user" in out
    assert "ready" in out


def test_cmd_setup_db_admin_failure_exits(capsys):
    """
    Input: admin connection (engine.connect) raises OperationalError
    Output: error printed; sys.exit(1)
    """
    from cli import cmd_setup_db

    mock_engine = MagicMock()
    mock_engine.connect.side_effect = Exception("access denied")
    mock_engine.dialect.identifier_preparer.quote = lambda x: f"`{x}`"

    with patch("cli._load_env"), \
         patch("flask_app.config.Config.MARIADB_HOST", "dbhost"), \
         patch("flask_app.config.Config.MARIADB_PORT", "3306"), \
         patch("flask_app.config.Config.MARIADB_DB", "shse"), \
         patch("flask_app.config.Config.MARIADB_USER", "shse_user"), \
         patch("flask_app.config.Config.MARIADB_PASSWORD", "secret"), \
         patch("sqlalchemy.create_engine", return_value=mock_engine):
        with pytest.raises(SystemExit) as exc:
            cmd_setup_db(_args(admin_user="root", admin_password="bad"))

    assert exc.value.code == 1


if __name__ == "__main__":
    pass
