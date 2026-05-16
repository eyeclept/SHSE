"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for flask_app/config_parser.py.
    Covers defaults inheritance, all five target types, schedule parsing,
    Celery Beat entry generation, and DB persistence.
    Persistence tests use an in-memory SQLite DB; no live MariaDB required.
"""
# Imports
import os

import pytest
from celery.schedules import crontab
from flask import Flask
from flask_app import db

# Globals
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "templates")
_STATIC_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "static")

_FULL_YAML = """\
defaults:
  service: http
  port: 80
  route: /
  tls_verify: true
  schedule:
    frequency: weekly
    day: sunday
    time: "02:00"
    timezone: UTC

targets:
  - type: network
    network: 192.168.1.0/24
    schedule:
      frequency: weekly
      day: sunday
      time: "02:00"
      timezone: America/New_York

  - type: service
    nickname: discourse
    url: discourse.lab.internal
    ip: 10.0.0.51
    port: 443
    tls_verify: false
    schedule:
      frequency: daily
      time: "03:00"
      timezone: UTC

  - type: oai-pmh
    nickname: invenio-rdm
    url: invenio.lab.internal
    endpoint: /oai2d
    schedule:
      frequency: daily
      time: "04:00"
      timezone: UTC

  - type: feed
    nickname: ghost-blog
    url: blog.lab.internal
    feed_path: /rss
    schedule:
      frequency: daily
      time: "04:30"
      timezone: UTC

  - type: api-push
    nickname: discourse-api
    url: discourse.lab.internal
    adapter: discourse_adapter
    schedule:
      frequency: monthly
      day: 1
      time: "01:00"
      timezone: UTC
"""


# Functions
@pytest.fixture
def sqlite_app():
    """
    Input: None
    Output: Flask test app with in-memory SQLite
    Details:
        Minimal app; does not call create_app(); avoids MariaDB.
    """
    from flask_app.models.search_history import SearchHistory      # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget      # noqa: F401
    from flask_app.models.crawl_job import CrawlJob                # noqa: F401
    from flask_app.models.user import User                         # noqa: F401
    from flask_app.models.system_setting import SystemSetting      # noqa: F401

    app = Flask(
        "test_yaml",
        template_folder=_TEMPLATE_DIR,
        static_folder=_STATIC_DIR,
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield app


@pytest.fixture
def db_session(sqlite_app):
    """
    Input: sqlite_app fixture
    Output: SQLAlchemy session bound to the in-memory DB
    """
    with sqlite_app.app_context():
        yield db.session


def test_defaults_inheritance():
    """
    Input: None
    Output: None
    Details:
        Fields omitted from a target are inherited from the defaults block.
    """
    from flask_app.config_parser import parse_config

    yaml_str = """\
defaults:
  service: http
  port: 80
  tls_verify: true
targets:
  - type: service
    nickname: myapp
    url: myapp.lab
"""
    targets = parse_config(yaml_str)
    assert len(targets) == 1
    t = targets[0]
    assert t["service"] == "http"
    assert t["port"] == 80
    assert t["tls_verify"] is True
    assert t["nickname"] == "myapp"


def test_target_overrides_default():
    """
    Input: None
    Output: None
    Details:
        A target value overrides the corresponding default.
    """
    from flask_app.config_parser import parse_config

    yaml_str = """\
defaults:
  port: 80
  tls_verify: true
targets:
  - type: service
    nickname: secure
    url: secure.lab
    port: 443
    tls_verify: false
"""
    targets = parse_config(yaml_str)
    t = targets[0]
    assert t["port"] == 443
    assert t["tls_verify"] is False


def test_schedule_deep_merge():
    """
    Input: None
    Output: None
    Details:
        A partial schedule override merges with defaults.schedule rather than
        replacing it; only the overridden keys change.
    """
    from flask_app.config_parser import parse_config

    yaml_str = """\
defaults:
  schedule:
    frequency: weekly
    day: sunday
    time: "02:00"
    timezone: UTC
targets:
  - type: network
    network: 10.0.0.0/24
    schedule:
      frequency: daily
      time: "06:00"
"""
    targets = parse_config(yaml_str)
    sched = targets[0]["schedule"]
    assert sched["frequency"] == "daily"
    assert sched["time"] == "06:00"
    assert sched["timezone"] == "UTC"   # inherited


def test_service_target():
    """
    Input: None
    Output: None
    Details:
        parse_config returns correct fields for a service target.
    """
    from flask_app.config_parser import parse_config

    targets = parse_config(_FULL_YAML)
    service = next(t for t in targets if t["type"] == "service")
    assert service["nickname"] == "discourse"
    assert service["url"] == "discourse.lab.internal"
    assert service["ip"] == "10.0.0.51"
    assert service["port"] == 443
    assert service["tls_verify"] is False


def test_network_target():
    """
    Input: None
    Output: None
    Details:
        parse_config returns correct fields for a network target.
    """
    from flask_app.config_parser import parse_config

    targets = parse_config(_FULL_YAML)
    net = next(t for t in targets if t["type"] == "network")
    assert net["network"] == "192.168.1.0/24"
    assert net["schedule"]["timezone"] == "America/New_York"


def test_oai_target():
    """
    Input: None
    Output: None
    Details:
        parse_config returns correct fields for an oai-pmh target.
    """
    from flask_app.config_parser import parse_config

    targets = parse_config(_FULL_YAML)
    oai = next(t for t in targets if t["type"] == "oai-pmh")
    assert oai["nickname"] == "invenio-rdm"
    assert oai["url"] == "invenio.lab.internal"
    assert oai["endpoint"] == "/oai2d"


def test_feed_target():
    """
    Input: None
    Output: None
    Details:
        parse_config returns correct fields for a feed target.
    """
    from flask_app.config_parser import parse_config

    targets = parse_config(_FULL_YAML)
    feed = next(t for t in targets if t["type"] == "feed")
    assert feed["nickname"] == "ghost-blog"
    assert feed["url"] == "blog.lab.internal"
    assert feed["feed_path"] == "/rss"


def test_api_push_target():
    """
    Input: None
    Output: None
    Details:
        parse_config returns correct fields for an api-push target.
    """
    from flask_app.config_parser import parse_config

    targets = parse_config(_FULL_YAML)
    push = next(t for t in targets if t["type"] == "api-push")
    assert push["nickname"] == "discourse-api"
    assert push["url"] == "discourse.lab.internal"
    assert push["adapter"] == "discourse_adapter"


def test_schedule_parsing_weekly():
    """
    Input: None
    Output: None
    Details:
        to_beat_entry converts a weekly schedule to a crontab with the correct
        hour (2), minute (0), and day_of_week (0 = Sunday).
    """
    from flask_app.config_parser import to_beat_entry

    target = {
        "type": "service",
        "nickname": "myblog",
        "schedule": {
            "frequency": "weekly",
            "day": "sunday",
            "time": "02:00",
            "timezone": "UTC",
        },
    }
    entry = to_beat_entry(target)
    assert entry is not None
    tab = entry["schedule"]
    assert isinstance(tab, crontab)
    assert 2 in tab.hour,   f"expected hour=2, got {tab.hour}"
    assert 0 in tab.minute, f"expected minute=0, got {tab.minute}"
    assert 0 in tab.day_of_week, f"expected day_of_week=0 (Sunday), got {tab.day_of_week}"
    assert entry["args"] == ["myblog"]
    assert entry["task"] == "celery_worker.tasks.crawl.crawl_target"


def test_schedule_parsing_daily():
    """
    Input: None
    Output: None
    Details:
        to_beat_entry converts a daily schedule with hour=3 and minute=30.
    """
    from flask_app.config_parser import to_beat_entry

    target = {
        "nickname": "myapp",
        "schedule": {"frequency": "daily", "time": "03:30"},
    }
    entry = to_beat_entry(target)
    tab = entry["schedule"]
    assert isinstance(tab, crontab)
    assert 3 in tab.hour,  f"expected hour=3, got {tab.hour}"
    assert 30 in tab.minute, f"expected minute=30, got {tab.minute}"


def test_schedule_parsing_monthly():
    """
    Input: None
    Output: None
    Details:
        to_beat_entry converts a monthly schedule with day_of_month=1, hour=1, minute=0.
    """
    from flask_app.config_parser import to_beat_entry

    target = {
        "nickname": "monthly-task",
        "schedule": {"frequency": "monthly", "day": 1, "time": "01:00"},
    }
    entry = to_beat_entry(target)
    tab = entry["schedule"]
    assert isinstance(tab, crontab)
    assert 1 in tab.day_of_month, f"expected day_of_month=1, got {tab.day_of_month}"
    assert 1 in tab.hour,         f"expected hour=1, got {tab.hour}"
    assert 0 in tab.minute,       f"expected minute=0, got {tab.minute}"


def test_no_schedule_returns_none():
    """
    Input: None
    Output: None
    Details:
        to_beat_entry returns None when the target has no schedule block.
    """
    from flask_app.config_parser import to_beat_entry

    assert to_beat_entry({"nickname": "x"}) is None


def test_persist_targets(db_session):
    """
    Input: None
    Output: None
    Details:
        persist_targets writes all five target types to the crawler_targets table.
    """
    from flask_app.config_parser import parse_config, persist_targets
    from flask_app.models.crawler_target import CrawlerTarget

    targets = parse_config(_FULL_YAML)
    created = persist_targets(_FULL_YAML, targets, db_session)

    assert len(created) == 5
    rows = db_session.query(CrawlerTarget).all()
    types = {r.target_type for r in rows}
    assert types == {"service", "network", "oai-pmh", "feed", "api-push"}

    oai = db_session.query(CrawlerTarget).filter_by(target_type="oai-pmh").first()
    assert oai.endpoint == "/oai2d"

    feed = db_session.query(CrawlerTarget).filter_by(target_type="feed").first()
    assert feed.feed_path == "/rss"

    push = db_session.query(CrawlerTarget).filter_by(target_type="api-push").first()
    assert push.adapter == "discourse_adapter"


def test_persist_replaces_existing(db_session):
    """
    Input: None
    Output: None
    Details:
        A second call to persist_targets replaces all existing rows (full replace).
    """
    from flask_app.config_parser import parse_config, persist_targets
    from flask_app.models.crawler_target import CrawlerTarget

    yaml1 = """\
defaults: {}
targets:
  - type: service
    nickname: old-app
    url: old.lab
"""
    yaml2 = """\
defaults: {}
targets:
  - type: network
    network: 10.0.0.0/8
"""
    persist_targets(yaml1, parse_config(yaml1), db_session)
    persist_targets(yaml2, parse_config(yaml2), db_session)

    rows = db_session.query(CrawlerTarget).all()
    assert len(rows) == 1
    assert rows[0].target_type == "network"


def test_persist_targets_with_existing_crawl_jobs(db_session):
    """
    Input: None
    Output: None
    Details:
        persist_targets must not fail with an IntegrityError when CrawlJob rows
        reference the targets being replaced. The FK fix nulls out CrawlJob.target_id
        before deleting CrawlerTarget rows. After the call:
          - old targets are gone
          - new targets are present
          - old CrawlJob rows survive with target_id=None
    """
    from flask_app.config_parser import parse_config, persist_targets
    from flask_app.models.crawler_target import CrawlerTarget
    from flask_app.models.crawl_job import CrawlJob

    yaml_v1 = """\
defaults: {}
targets:
  - type: service
    nickname: svc-a
    url: svc-a.lab
"""
    # First upload — creates a target
    persist_targets(yaml_v1, parse_config(yaml_v1), db_session)
    target = db_session.query(CrawlerTarget).filter_by(nickname="svc-a").first()
    assert target is not None

    # Simulate a CrawlJob referencing that target
    job = CrawlJob(target_id=target.id, status="success")
    db_session.add(job)
    db_session.commit()
    job_id = job.id

    yaml_v2 = """\
defaults: {}
targets:
  - type: network
    network: 10.0.0.0/8
"""
    # Second upload — must not raise IntegrityError despite existing CrawlJob
    persist_targets(yaml_v2, parse_config(yaml_v2), db_session)

    # Old targets replaced
    remaining = db_session.query(CrawlerTarget).all()
    assert len(remaining) == 1
    assert remaining[0].target_type == "network"

    # CrawlJob row survives with target_id nulled out
    orphaned_job = db_session.get(CrawlJob, job_id)
    assert orphaned_job is not None
    assert orphaned_job.target_id is None


def test_celery_beat_entries():
    """
    Input: None
    Output: None
    Details:
        to_beat_entry returns a valid entry for every target that has a schedule.
    """
    from flask_app.config_parser import parse_config, to_beat_entry

    targets = parse_config(_FULL_YAML)
    entries = [to_beat_entry(t) for t in targets if t.get("schedule")]
    assert len(entries) == 5
    assert all(e is not None for e in entries)
    assert all("schedule" in e for e in entries)
    assert all(isinstance(e["schedule"], crontab) for e in entries)


def test_parse_llm_settings_extracts_block():
    """
    Input:  YAML with a settings.llm block
    Output: dict containing gen_model, embed_model, summary_template
    """
    from flask_app.config_parser import parse_llm_settings

    yaml_str = """\
defaults: {}
targets: []
settings:
  llm:
    embed_model: nomic-embed-text
    gen_model: granite3.3:latest
    summary_template: "Answer: {context} Q: {query}"
"""
    result = parse_llm_settings(yaml_str)
    assert result["embed_model"] == "nomic-embed-text"
    assert result["gen_model"] == "granite3.3:latest"
    assert "{context}" in result["summary_template"]
    assert "{query}" in result["summary_template"]


def test_parse_llm_settings_empty_when_absent():
    """
    Input:  YAML without a settings block
    Output: empty dict
    """
    from flask_app.config_parser import parse_llm_settings

    result = parse_llm_settings("defaults: {}\ntargets: []\n")
    assert result == {}


def test_persist_targets_writes_llm_settings(db_session):
    """
    Input:  YAML with settings.llm block
    Output: system_settings rows written for llm.gen_model and llm.embed_model
    """
    from flask_app.config_parser import parse_config, persist_targets
    from flask_app.models.system_setting import SystemSetting

    yaml_str = """\
defaults: {}
targets:
  - type: service
    nickname: svc
    url: lab.internal
settings:
  llm:
    gen_model: granite3.3:latest
    embed_model: nomic-embed-text
"""
    persist_targets(yaml_str, parse_config(yaml_str), db_session)

    gen = db_session.get(SystemSetting, "llm.gen_model")
    emb = db_session.get(SystemSetting, "llm.embed_model")
    assert gen is not None and gen.value == "granite3.3:latest"
    assert emb is not None and emb.value == "nomic-embed-text"


def test_persist_targets_llm_settings_update_on_second_upload(db_session):
    """
    Input:  Two sequential uploads with different gen_model values
    Output: DB row updated to the second value (upsert behaviour)
    """
    from flask_app.config_parser import parse_config, persist_targets
    from flask_app.models.system_setting import SystemSetting

    yaml1 = "defaults: {}\ntargets: []\nsettings:\n  llm:\n    gen_model: modelA\n"
    yaml2 = "defaults: {}\ntargets: []\nsettings:\n  llm:\n    gen_model: modelB\n"

    persist_targets(yaml1, parse_config(yaml1), db_session)
    persist_targets(yaml2, parse_config(yaml2), db_session)

    row = db_session.get(SystemSetting, "llm.gen_model")
    assert row.value == "modelB"


def test_parse_llm_settings_malformed_yaml_returns_empty():
    """
    Input:  Deliberately broken YAML string (tab where space required)
    Output: empty dict — parse_llm_settings catches YAMLError and returns {}
    Details:
        parse_llm_settings must never raise on malformed input; callers rely
        on the empty-dict fallback to proceed with env-var defaults.
    """
    from flask_app.config_parser import parse_llm_settings
    bad_yaml = "settings:\n\tllm:\n\t\tgen_model: foo\n"
    result = parse_llm_settings(bad_yaml)
    assert result == {}, f"Expected empty dict, got: {result}"


def test_parse_config_malformed_yaml_raises_value_error():
    """
    Input:  Deliberately broken YAML string
    Output: ValueError raised — parse_config propagates malformed input as ValueError
    Details:
        parse_config must raise ValueError (not bare YAMLError) so callers can
        catch a stable exception type without importing yaml directly.
    """
    from flask_app.config_parser import parse_config
    bad_yaml = "targets:\n\tbroken: yes\n"
    with pytest.raises(ValueError, match="invalid YAML"):
        parse_config(bad_yaml)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
