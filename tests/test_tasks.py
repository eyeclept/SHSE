"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for Celery tasks in celery_worker/tasks/.
    All tests use in-memory SQLite and mock external services;
    no live MariaDB, Nutch, OpenSearch, or LLM API required.
"""
# Imports
import os
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask_app import db

# Globals
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "templates")
_STATIC_DIR = os.path.join(_PROJECT_ROOT, "flask_app", "static")


# Functions
@pytest.fixture
def sqlite_app():
    """
    Input: None
    Output: Flask test app with in-memory SQLite
    Details:
        Imports all models so create_all() registers every table.
    """
    from flask_app.models.user import User                     # noqa: F401
    from flask_app.models.search_history import SearchHistory  # noqa: F401
    from flask_app.models.crawler_target import CrawlerTarget  # noqa: F401
    from flask_app.models.crawl_job import CrawlJob            # noqa: F401

    app = Flask(
        "test_tasks",
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
    Output: SQLAlchemy session bound to in-memory SQLite
    """
    with sqlite_app.app_context():
        yield db.session


@pytest.fixture
def service_target(db_session):
    """
    Input: db_session fixture
    Output: CrawlerTarget of type 'service' persisted in SQLite
    """
    from flask_app.models.crawler_target import CrawlerTarget
    t = CrawlerTarget(
        nickname="testsvc",
        target_type="service",
        url="svc.lab",
        port=80,
        route="/",
        service="http",
        tls_verify=True,
    )
    db_session.add(t)
    db_session.commit()
    return t


@pytest.fixture
def oai_target(db_session):
    """
    Input: db_session fixture
    Output: CrawlerTarget of type 'oai-pmh' persisted in SQLite
    """
    from flask_app.models.crawler_target import CrawlerTarget
    t = CrawlerTarget(
        nickname="myoai",
        target_type="oai-pmh",
        url="oai.lab",
        endpoint="/oai2d",
    )
    db_session.add(t)
    db_session.commit()
    return t


@pytest.fixture
def feed_target(db_session):
    """
    Input: db_session fixture
    Output: CrawlerTarget of type 'feed' persisted in SQLite
    """
    from flask_app.models.crawler_target import CrawlerTarget
    t = CrawlerTarget(
        nickname="myfeed",
        target_type="feed",
        url="blog.lab",
        feed_path="/rss",
    )
    db_session.add(t)
    db_session.commit()
    return t


@pytest.fixture
def push_target(db_session):
    """
    Input: db_session fixture
    Output: CrawlerTarget of type 'api-push' persisted in SQLite
    """
    from flask_app.models.crawler_target import CrawlerTarget
    t = CrawlerTarget(
        nickname="mypush",
        target_type="api-push",
        url="api.lab",
        adapter="discourse_adapter",
    )
    db_session.add(t)
    db_session.commit()
    return t


def test_crawl_target_creates_crawl_job(db_session, service_target):
    """
    Input: None
    Output: None
    Details:
        crawl_target creates a CrawlJob row and sets status to success.
    """
    from flask_app.models.crawl_job import CrawlJob
    from celery_worker.tasks.crawl import _crawl_target_impl

    os_client = MagicMock()

    with patch("celery_worker.tasks.crawl.trigger_crawl", return_value="c-001"), \
         patch("celery_worker.tasks.crawl.fetch_results", return_value={"nodes": []}), \
         patch("celery_worker.tasks.crawl.delete_stale"):
        job_id = _crawl_target_impl(
            service_target.id, db_session, None, os_client
        )

    job = db_session.get(CrawlJob, job_id)
    assert job is not None
    assert job.target_id == service_target.id
    assert job.status == "success"
    assert job.started_at is not None
    assert job.finished_at is not None


def test_crawl_target_status_failure_on_exception(db_session, service_target):
    """
    Input: None
    Output: None
    Details:
        When the crawl raises, CrawlJob status is set to failure.
    """
    from flask_app.models.crawl_job import CrawlJob
    from celery_worker.tasks.crawl import _crawl_target_impl

    with patch(
        "celery_worker.tasks.crawl.trigger_crawl",
        side_effect=RuntimeError("nutch down"),
    ), pytest.raises(RuntimeError):
        _crawl_target_impl(service_target.id, db_session)

    job = db_session.query(CrawlJob).filter_by(target_id=service_target.id).first()
    assert job.status == "failure"


def test_crawl_all_dispatches_one_per_target(db_session):
    """
    Input: None
    Output: None
    Details:
        crawl_all dispatches exactly one crawl_target.delay() call per target,
        passing each target's actual DB id.
    """
    from flask_app.models.crawler_target import CrawlerTarget
    from celery_worker.tasks.crawl import crawl_all

    targets = []
    for i in range(3):
        t = CrawlerTarget(nickname=f"svc{i}", target_type="service", url=f"svc{i}.lab")
        db_session.add(t)
        targets.append(t)
    db_session.commit()

    mock_result = MagicMock()
    mock_result.id = "task-abc"

    with patch("celery_worker.tasks.crawl.crawl_target") as mock_task:
        mock_task.delay.return_value = mock_result
        result = crawl_all(_db_session=db_session)

    assert mock_task.delay.call_count == 3
    assert len(result) == 3
    dispatched_ids = {call.args[0] for call in mock_task.delay.call_args_list}
    expected_ids = {t.id for t in targets}
    assert dispatched_ids == expected_ids


def test_reindex_target_deletes_then_crawls(db_session, service_target):
    """
    Input: None
    Output: None
    Details:
        reindex_target deletes existing OpenSearch docs then triggers a crawl.
        Verified by: delete_by_nickname is called at the opensearch module level
        and a CrawlJob is written with status success.
    """
    from flask_app.models.crawl_job import CrawlJob
    from celery_worker.tasks.index import reindex_target

    os_client = MagicMock()

    with patch("celery_worker.tasks.index.delete_by_nickname") as del_mock, \
         patch("celery_worker.tasks.crawl.trigger_crawl", return_value="c-001"), \
         patch("celery_worker.tasks.crawl.fetch_results", return_value={"nodes": []}), \
         patch("celery_worker.tasks.crawl.delete_stale"):
        reindex_target(
            service_target.id,
            _db_session=db_session,
            _os_client=os_client,
        )

    del_mock.assert_called_once()
    job = db_session.query(CrawlJob).filter_by(target_id=service_target.id).first()
    assert job is not None
    assert job.status == "success"


def test_reindex_all_wipes_then_crawls_all(db_session):
    """
    Input: None
    Output: None
    Details:
        reindex_all calls wipe_index then dispatches crawl_target.delay per target.
    """
    from flask_app.models.crawler_target import CrawlerTarget
    from celery_worker.tasks.index import reindex_all

    for i in range(2):
        db_session.add(CrawlerTarget(
            nickname=f"t{i}", target_type="service", url=f"t{i}.lab"
        ))
    db_session.commit()

    mock_result = MagicMock()
    mock_result.id = "task-xyz"

    with patch("celery_worker.tasks.index.wipe_index") as wipe_mock, \
         patch("celery_worker.tasks.index.crawl_target") as task_mock:
        task_mock.delay.return_value = mock_result
        reindex_all(_db_session=db_session)

    wipe_mock.assert_called_once()
    assert task_mock.delay.call_count == 2


def test_vectorize_pending_embeds_all_docs():
    """
    Input: None
    Output: None
    Details:
        vectorize_pending calls get_embedding for each unvectorized doc and
        issues a client.update for each successful embedding.
    """
    from celery_worker.tasks.vectorize import _vectorize_pending_impl

    hits = [
        {"_id": "id1", "_source": {"text": "hello world"}},
        {"_id": "id2", "_source": {"text": "foo bar"}},
    ]
    os_client = MagicMock()
    os_client.search.side_effect = [
        {"hits": {"hits": hits}},
        {"hits": {"hits": []}},
    ]
    llm_session = MagicMock()
    embed_resp = MagicMock()
    embed_resp.raise_for_status.return_value = None
    embed_resp.json.return_value = {"data": [{"embedding": [0.1] * 768}]}
    llm_session.post.return_value = embed_resp

    count = _vectorize_pending_impl(
        os_client=os_client, llm_session=llm_session, page_size=10
    )

    assert count == 2
    assert os_client.update.call_count == 2
    call_body = os_client.update.call_args_list[0].kwargs["body"]
    assert call_body["doc"]["vectorized"] is True
    assert len(call_body["doc"]["embedding"]) == 768


def test_vectorize_pending_skips_on_llm_failure():
    """
    Input: None
    Output: None
    Details:
        When get_embedding returns None, the doc is left unmodified (no update call).
    """
    from celery_worker.tasks.vectorize import _vectorize_pending_impl

    hits = [{"_id": "id1", "_source": {"text": "hello"}}]
    os_client = MagicMock()
    os_client.search.side_effect = [
        {"hits": {"hits": hits}},
        {"hits": {"hits": []}},
    ]
    llm_session = MagicMock()
    llm_session.post.side_effect = ConnectionError("unreachable")

    count = _vectorize_pending_impl(
        os_client=os_client, llm_session=llm_session, page_size=10
    )

    assert count == 0
    os_client.update.assert_not_called()


def test_scheduled_crawl_dispatches_by_nickname(db_session, service_target):
    """
    Input: None
    Output: None
    Details:
        scheduled_crawl looks up the target by nickname and calls _crawl_target_impl
        with the correct target_id as the first positional argument.
    """
    from celery_worker.tasks.crawl import scheduled_crawl
    from unittest.mock import call as mock_call

    with patch("celery_worker.tasks.crawl._crawl_target_impl", return_value=42) as impl_mock:
        result = scheduled_crawl("testsvc", _db_session=db_session)

    assert result == 42
    impl_mock.assert_called_once()
    called_target_id = impl_mock.call_args.args[0]
    assert called_target_id == service_target.id, (
        f"expected target_id={service_target.id}, got {called_target_id}"
    )


def test_scheduled_crawl_unknown_nickname_returns_none(db_session):
    """
    Input: None
    Output: None
    Details:
        scheduled_crawl returns None when no target matches the given nickname.
    """
    from celery_worker.tasks.crawl import scheduled_crawl

    result = scheduled_crawl("does-not-exist", _db_session=db_session)
    assert result is None


def test_harvest_oai_uses_correct_source_type(db_session, oai_target):
    """
    Input: None
    Output: None
    Details:
        _harvest_oai_impl calls index_document with source_type='oai-pmh'
        when docs are provided via _docs injection.
    """
    from celery_worker.tasks.crawl import _harvest_oai_impl

    fake_docs = [{"url": "http://oai.lab/rec1", "title": "Rec 1", "text": "content"}]
    os_client = MagicMock()

    with patch("celery_worker.tasks.crawl.index_document") as idx_mock, \
         patch("celery_worker.tasks.crawl.delete_stale"):
        _harvest_oai_impl(oai_target, os_client=os_client, _docs=fake_docs)

    idx_mock.assert_called_once()
    assert idx_mock.call_args.kwargs["source_type"] == "oai-pmh"
    assert idx_mock.call_args.kwargs["service_nickname"] == "myoai"


def test_harvest_feeds_uses_correct_source_type(db_session, feed_target):
    """
    Input: None
    Output: None
    Details:
        _harvest_feeds_impl calls index_document with source_type='rss'.
    """
    from celery_worker.tasks.crawl import _harvest_feeds_impl

    fake_docs = [{"url": "http://blog.lab/post1", "title": "Post 1", "text": "body"}]
    os_client = MagicMock()

    with patch("celery_worker.tasks.crawl.index_document") as idx_mock, \
         patch("celery_worker.tasks.crawl.delete_stale"):
        _harvest_feeds_impl(feed_target, os_client=os_client, _docs=fake_docs)

    idx_mock.assert_called_once()
    assert idx_mock.call_args.kwargs["source_type"] == "rss"


def test_push_api_content_uses_correct_source_type(db_session, push_target):
    """
    Input: None
    Output: None
    Details:
        _push_api_content_impl calls index_document with source_type='api-push'.
    """
    from celery_worker.tasks.crawl import _push_api_content_impl

    fake_docs = [{"url": "http://api.lab/item1", "title": "Item", "text": "data"}]
    os_client = MagicMock()

    with patch("celery_worker.tasks.crawl.index_document") as idx_mock, \
         patch("celery_worker.tasks.crawl.delete_stale"):
        _push_api_content_impl(push_target, os_client=os_client, _docs=fake_docs)

    idx_mock.assert_called_once()
    assert idx_mock.call_args.kwargs["source_type"] == "api-push"


def test_crawl_job_lifecycle(db_session, service_target):
    """
    Input: None
    Output: None
    Details:
        CrawlJob row transitions: created with status started, finishes as success.
    """
    from flask_app.models.crawl_job import CrawlJob
    from celery_worker.tasks.crawl import _crawl_target_impl

    os_client = MagicMock()

    with patch("celery_worker.tasks.crawl.trigger_crawl", return_value="c-001"), \
         patch("celery_worker.tasks.crawl.fetch_results", return_value={"nodes": []}), \
         patch("celery_worker.tasks.crawl.delete_stale"):
        job_id = _crawl_target_impl(service_target.id, db_session, None, os_client)

    jobs = db_session.query(CrawlJob).filter_by(target_id=service_target.id).all()
    assert len(jobs) == 1
    assert jobs[0].status == "success"
    assert jobs[0].started_at is not None
    assert jobs[0].finished_at is not None


def test_beat_schedule_loaded_from_db(db_session):
    """
    Input: None
    Output: None
    Details:
        load_beat_schedule() reads CrawlerTarget rows with schedule_yaml set,
        converts them to crontab entries, and sets celery.conf.beat_schedule.
        Targets without schedule_yaml are skipped.
    """
    import yaml
    from celery.schedules import crontab
    from flask_app.models.crawler_target import CrawlerTarget
    from celery_worker.app import celery, load_beat_schedule

    sched = {"frequency": "daily", "time": "03:00"}
    t1 = CrawlerTarget(
        nickname="sched-svc",
        target_type="service",
        url="svc.lab",
        schedule_yaml=yaml.dump(sched),
    )
    t2 = CrawlerTarget(
        nickname="no-sched-svc",
        target_type="service",
        url="svc2.lab",
        schedule_yaml=None,
    )
    db_session.add_all([t1, t2])
    db_session.commit()

    load_beat_schedule(_db_session=db_session)

    assert "sched-svc" in celery.conf.beat_schedule
    entry = celery.conf.beat_schedule["sched-svc"]
    assert isinstance(entry["schedule"], crontab)
    assert 3 in entry["schedule"].hour
    assert 0 in entry["schedule"].minute
    assert entry["task"] == "celery_worker.tasks.crawl.crawl_target"
    assert entry["args"] == ["sched-svc"]

    # Target with no schedule_yaml must not appear
    assert "no-sched-svc" not in celery.conf.beat_schedule


if __name__ == "__main__":
    import pytest as _pytest
    _pytest.main([__file__, "-v"])
