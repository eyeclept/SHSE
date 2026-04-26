"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Celery application instance. Redis is the broker.
    Beat handles scheduled crawls defined in the YAML crawler config.
"""
# Imports
import os

from celery import Celery

# Globals
_REDIS_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")

celery = Celery(
    "shse",
    broker=_REDIS_URL,
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

    def _build(db_session):
        targets = db_session.query(CrawlerTarget).all()
        schedule = {}
        for t in targets:
            if not t.schedule_yaml:
                continue
            try:
                sched_dict = _yaml.safe_load(t.schedule_yaml)
            except Exception:
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
        pass


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
