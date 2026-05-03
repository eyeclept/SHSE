"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Celery application instance. Redis is the broker.
    Beat handles scheduled crawls defined in the YAML crawler config.
"""
# Imports
import logging
import os
from logging.handlers import RotatingFileHandler

from celery import Celery

# Globals
_REDIS_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")

_log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(_log_dir, exist_ok=True)
_fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
_celery_handler = RotatingFileHandler(
    os.path.join(_log_dir, "celery.log"), maxBytes=5 * 1024 * 1024, backupCount=3
)
_celery_handler.setFormatter(logging.Formatter(_fmt))
logging.root.setLevel(logging.INFO)
logging.root.addHandler(_celery_handler)

celery = Celery(
    "shse",
    broker=_REDIS_URL,
    backend=_REDIS_URL,   # store task results so job logs are readable
    include=[
        "celery_worker.tasks.crawl",
        "celery_worker.tasks.index",
        "celery_worker.tasks.vectorize",
    ],
)

# Use redbeat for persistent Beat scheduling so run-history survives restarts.
# Beat will fire any overdue tasks on startup rather than skipping them.
celery.conf.update(
    beat_scheduler="redbeat.RedBeatScheduler",
    redbeat_redis_url=_REDIS_URL,
    redbeat_lock_timeout=60,   # seconds; prevents stale lock if Beat crashes
)


# Functions
def load_beat_schedule(_db_session=None):
    """
    Input:
        _db_session - injectable SQLAlchemy session (tests only); when None
                      a Flask app context is created and db.session is used
    Output: None
    Details:
        Reads all CrawlerTarget rows from MariaDB, calls to_beat_entry() on each,
        and populates celery.conf.beat_schedule. Targets with no schedule_yaml
        are skipped. Failures are swallowed so Beat starts cleanly even when
        the DB is temporarily unreachable.
    """
    import yaml as _yaml
    from flask_app.config_parser import to_beat_entry
    from flask_app.models.crawler_target import CrawlerTarget

    _logger = logging.getLogger(__name__)

    def _build(db_session):
        targets = db_session.query(CrawlerTarget).all()
        schedule = {}
        for t in targets:
            if not t.schedule_yaml:
                continue
            try:
                sched_dict = _yaml.safe_load(t.schedule_yaml)
            except Exception:
                _logger.warning(
                    "load_beat_schedule: malformed schedule_yaml for target %s — skipping",
                    t.nickname or t.id,
                    exc_info=True,
                )
                continue
            entry = to_beat_entry({
                "type": t.target_type,
                "nickname": t.nickname,
                "network": t.network,
                "schedule": sched_dict,
            })
            if entry:
                key = t.nickname or t.network or str(t.id)
                schedule[key] = entry
        celery.conf.beat_schedule = schedule

    try:
        if _db_session is not None:
            _build(_db_session)
            return
        from flask_app import create_app, db
        app = create_app()
        with app.app_context():
            _build(db.session)
    except Exception:
        _logger.exception("load_beat_schedule failed — Beat starts with empty schedule")


@celery.on_after_finalize.connect
def setup_beat_schedule(sender, **kwargs):
    """
    Input: Celery on_after_finalize signal
    Output: None
    Details:
        Signal hook that triggers beat schedule population after all tasks
        are registered. Only has effect when Beat is running.
    """
    load_beat_schedule()


def main():
    """
    Input: None
    Output: None
    Details:
        Placeholder entry point.
    """
    pass


if __name__ == "__main__":
    main()
