"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    YAML crawler configuration parser.
    Parses the declarative YAML config format, applies defaults inheritance,
    persists targets to the crawler_targets table, and converts schedule blocks
    to Celery Beat crontab entries.

    Target types: service, network, oai-pmh, feed, api-push.
    Any field omitted from a target is inherited from the top-level defaults block.
"""
# Imports
import copy
import logging

import yaml
from celery.schedules import crontab

# Globals
logger = logging.getLogger(__name__)

_DAYS_OF_WEEK = {
    "monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4,
    "friday": 5, "saturday": 6, "sunday": 0,
}


# Functions
def _deep_merge(base, override):
    """
    Input:
        base     - dict, the defaults (modified in place)
        override - dict, target-level values that take precedence
    Output:
        dict - merged result (same object as base)
    Details:
        Recursively merges override into base. Only dicts are merged
        recursively; all other types are replaced by the override value.
    """
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def parse_llm_settings(yaml_str):
    """
    Input:  yaml_str — str, YAML configuration string
    Output: dict with keys embed_model, gen_model, summary_template (all optional)
    Details:
        Extracts the settings.llm block from the YAML document.
        Returns an empty dict if the block is absent or malformed.
    """
    try:
        doc = yaml.safe_load(yaml_str) or {}
    except yaml.YAMLError as e:
        logger.exception("malformed YAML in parse_llm_settings: %s", e)
        return {}
    return doc.get("settings", {}).get("llm", {})


def parse_config(yaml_str):
    """
    Input:
        yaml_str - str, YAML configuration string
    Output:
        list[dict] of resolved target configurations (defaults applied)
    Details:
        Parses the YAML document, extracts the defaults block, and deep-merges
        defaults into each target so that every target dict contains all fields.
        Does not validate field presence; callers are responsible for checking
        required fields per target type.
        Raises ValueError for malformed YAML input.
    """
    try:
        doc = yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        logger.exception("malformed YAML in parse_config: %s", e)
        raise ValueError("invalid YAML") from e
    defaults = doc.get("defaults", {})
    raw_targets = doc.get("targets", [])

    resolved = []
    for target in raw_targets:
        base = copy.deepcopy(defaults)
        merged = _deep_merge(base, target)
        resolved.append(merged)
    return resolved


def parse_service_target(target):
    """
    Input:
        target - dict, resolved target with type 'service'
    Output:
        dict with keys: nickname, url, ip, port, route, service, tls_verify, schedule
    Details:
        Extracts and returns only the fields relevant to a service target.
        Missing optional fields default to None.
    """
    return {
        "type": "service",
        "nickname": target.get("nickname"),
        "url": target.get("url"),
        "ip": target.get("ip"),
        "port": target.get("port"),
        "route": target.get("route", "/"),
        "service": target.get("service", "http"),
        "tls_verify": target.get("tls_verify", True),
        "crawl_depth": target.get("crawl_depth", 2),
        "schedule": target.get("schedule"),
    }


def parse_network_target(target):
    """
    Input:
        target - dict, resolved target with type 'network'
    Output:
        dict with keys: network, schedule
    Details:
        Extracts and returns only the fields relevant to a network target.
    """
    return {
        "type": "network",
        "network": target.get("network"),
        "crawl_depth": target.get("crawl_depth", 2),
        "schedule": target.get("schedule"),
    }


def parse_oai_target(target):
    """
    Input:
        target - dict, resolved target with type 'oai-pmh'
    Output:
        dict with keys: nickname, url, endpoint, schedule
    Details:
        Extracts fields for an OAI-PMH Metha harvest target.
    """
    return {
        "type": "oai-pmh",
        "nickname": target.get("nickname"),
        "url": target.get("url"),
        "endpoint": target.get("endpoint"),
        "schedule": target.get("schedule"),
    }


def parse_feed_target(target):
    """
    Input:
        target - dict, resolved target with type 'feed'
    Output:
        dict with keys: nickname, url, feed_path, schedule
    Details:
        Extracts fields for an RSS/Atom/ActivityPub feed target.
    """
    return {
        "type": "feed",
        "nickname": target.get("nickname"),
        "url": target.get("url"),
        "feed_path": target.get("feed_path"),
        "schedule": target.get("schedule"),
    }


def parse_api_push_target(target):
    """
    Input:
        target - dict, resolved target with type 'api-push'
    Output:
        dict with keys: nickname, url, adapter, schedule
    Details:
        Extracts fields for an api-push custom adapter target.
    """
    return {
        "type": "api-push",
        "nickname": target.get("nickname"),
        "url": target.get("url"),
        "adapter": target.get("adapter"),
        "schedule": target.get("schedule"),
    }


def to_beat_entry(target):
    """
    Input:
        target - dict, resolved target dict (as returned by parse_config)
    Output:
        dict with keys 'task', 'schedule' (crontab), 'args' ([target nickname])
        suitable for inclusion in a Celery Beat CELERYBEAT_SCHEDULE dict.
        Returns None if the target has no schedule block.
    Details:
        Converts the YAML schedule block to a Celery crontab.
        Supported frequencies: hourly, daily, weekly, monthly.
        Time is parsed from the 'time' field (HH:MM format).
        Day-of-week is parsed from 'day' (name or 0-6).
        Day-of-month is parsed from 'day' (integer) for monthly frequency.
    """
    schedule_block = target.get("schedule")
    if not schedule_block:
        return None

    frequency = schedule_block.get("frequency", "daily")
    time_str = schedule_block.get("time", "00:00")
    hour, minute = (int(p) for p in time_str.split(":"))

    if frequency == "hourly":
        tab = crontab(minute=minute)
    elif frequency == "daily":
        tab = crontab(hour=hour, minute=minute)
    elif frequency == "weekly":
        day_raw = str(schedule_block.get("day", "sunday")).lower()
        dow = _DAYS_OF_WEEK.get(day_raw, day_raw)
        tab = crontab(hour=hour, minute=minute, day_of_week=dow)
    elif frequency == "monthly":
        dom = schedule_block.get("day", 1)
        tab = crontab(hour=hour, minute=minute, day_of_month=dom)
    else:
        tab = crontab(hour=hour, minute=minute)

    nickname = target.get("nickname") or target.get("network", "unnamed")
    return {
        "task": "celery_worker.tasks.crawl.crawl_target",
        "schedule": tab,
        "args": [nickname],
    }


def persist_targets(yaml_str, parsed_targets, db_session):
    """
    Input:
        yaml_str       - str, raw YAML blob to store on each target row
        parsed_targets - list[dict], as returned by parse_config
        db_session     - SQLAlchemy session (injectable for tests)
    Output:
        list[CrawlerTarget] — newly created ORM objects after commit
    Details:
        Deletes all existing rows (full replace on upload), then inserts one
        row per resolved target. yaml_source stores the raw YAML blob.
        schedule_yaml stores the serialised schedule block for the target.
    """
    from flask_app.models.crawler_target import CrawlerTarget
    from flask_app.models.crawl_job import CrawlJob
    from flask_app.models.system_setting import SystemSetting

    # Null out target references before deleting targets to satisfy the FK constraint.
    # Jobs are preserved for audit purposes; target_id becomes NULL.
    db_session.query(CrawlJob).filter(CrawlJob.target_id.isnot(None)).update(
        {"target_id": None}, synchronize_session="fetch"
    )
    db_session.query(CrawlerTarget).delete(synchronize_session="fetch")

    created = []
    for t in parsed_targets:
        schedule = t.get("schedule")
        row = CrawlerTarget(
            nickname=t.get("nickname"),
            target_type=t["type"],
            url=t.get("url"),
            ip=t.get("ip"),
            network=t.get("network"),
            port=t.get("port"),
            route=t.get("route"),
            service=t.get("service"),
            tls_verify=t.get("tls_verify", True),
            crawl_depth=t.get("crawl_depth", 2),
            endpoint=t.get("endpoint"),
            feed_path=t.get("feed_path"),
            adapter=t.get("adapter"),
            schedule_yaml=yaml.dump(schedule) if schedule else None,
            yaml_source=yaml_str,
        )
        db_session.add(row)
        created.append(row)

    db_session.commit()

    llm = parse_llm_settings(yaml_str)
    for field in ("embed_model", "gen_model", "summary_template"):
        if field in llm:
            k = f"llm.{field}"
            row = db_session.get(SystemSetting, k)
            if row is None:
                db_session.add(SystemSetting(key=k, value=str(llm[field])))
            else:
                row.value = str(llm[field])
    if llm:
        db_session.commit()

    return created


if __name__ == "__main__":
    pass
