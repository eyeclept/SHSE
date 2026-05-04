"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    SHSE admin CLI. Provides command-line access to crawl management,
    index operations, crawler config, and job status.

    Requires the Docker stack (MariaDB, Redis, OpenSearch) to be running.
    Celery tasks are dispatched asynchronously; the CLI prints the task ID
    and returns immediately. The Celery worker processes the task in the background.

Usage:
    python cli.py <command> [args]
    python cli.py --help
"""
# Imports
import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)

# Globals
_COMMANDS = {}


# Functions
def _load_env():
    """
    Input: None
    Output: None
    Details:
        Loads .env from the project root into the environment.
        Safe to call multiple times; python-dotenv skips already-set vars.
    """
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def _get_app():
    """
    Input: None
    Output: (Flask app, db)
    Details:
        Creates and returns a Flask app instance for DB access.
        Called lazily so import-time errors surface only when a command runs.
    """
    from flask_app import create_app, db
    return create_app(), db


def _lookup_target(db_session, nickname):
    """
    Input: db_session, nickname str
    Output: CrawlerTarget ORM object
    Details:
        Exits with an error message if no target with that nickname exists.
    """
    from flask_app.models.crawler_target import CrawlerTarget
    target = db_session.query(CrawlerTarget).filter_by(nickname=nickname).first()
    if target is None:
        print(f"error: no target with nickname '{nickname}'", file=sys.stderr)
        sys.exit(1)
    return target


def cmd_stats(_args):
    """
    Input: parsed args (unused)
    Output: prints index stats to stdout
    Details:
        Queries OpenSearch for document count, service count, and last crawl time.
    """
    _load_env()
    from flask_app.services.opensearch import get_client
    try:
        client = get_client()
        count = client.count(index="shse_pages").get("count", 0)
        agg = client.search(index="shse_pages", body={
            "size": 0,
            "aggs": {"svc": {"cardinality": {"field": "service_nickname.keyword"}}},
        })
        svc_count = agg["aggregations"]["svc"]["value"]
        last = client.search(index="shse_pages", body={
            "size": 1, "sort": [{"crawled_at": "desc"}], "_source": ["crawled_at"],
        })
        hits = last["hits"]["hits"]
        last_crawl = hits[0]["_source"].get("crawled_at", "never")[:19] if hits else "never"
        print(f"documents : {count:,}")
        print(f"services  : {svc_count}")
        print(f"last crawl: {last_crawl}")
    except Exception as exc:
        print(f"error: could not reach OpenSearch — {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_list_targets(_args):
    """
    Input: parsed args (unused)
    Output: prints all crawler targets to stdout
    Details:
        Lists each target's id, nickname, type, url/network, and schedule frequency.
    """
    _load_env()
    app, db = _get_app()
    with app.app_context():
        from flask_app.models.crawler_target import CrawlerTarget
        import yaml as _yaml
        targets = db.session.query(CrawlerTarget).order_by(CrawlerTarget.id).all()
        if not targets:
            print("no targets configured")
            return
        fmt = "{:<4}  {:<24}  {:<10}  {:<32}  {}"
        print(fmt.format("id", "nickname", "type", "url / network", "schedule"))
        print("-" * 90)
        for t in targets:
            addr = t.url or t.network or ""
            sched = ""
            if t.schedule_yaml:
                try:
                    s = _yaml.safe_load(t.schedule_yaml)
                    sched = s.get("frequency", "") if s else ""
                except Exception:
                    logger.warning("list-targets: malformed schedule_yaml for target %s", t.id, exc_info=True)
            print(fmt.format(
                t.id,
                (t.nickname or "")[:24],
                t.target_type[:10],
                addr[:32],
                sched,
            ))


def cmd_upload_config(args):
    """
    Input: args.file — path to YAML config file
    Output: prints count of persisted targets
    Details:
        Parses the YAML file and replaces all existing crawler targets in MariaDB.
        Existing CrawlJob rows are preserved with target_id nulled out.
    """
    _load_env()
    path = args.file
    if not os.path.isfile(path):
        print(f"error: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        yaml_str = f.read()

    from flask_app.config_parser import parse_config, persist_targets
    try:
        parsed = parse_config(yaml_str)
    except Exception as exc:
        print(f"error: YAML parse failed — {exc}", file=sys.stderr)
        sys.exit(1)

    app, db = _get_app()
    with app.app_context():
        created = persist_targets(yaml_str, parsed, db.session)
        print(f"persisted {len(created)} target(s)")
        for t in created:
            print(f"  {t.id:>4}  {t.target_type:<10}  {t.nickname or t.network or ''}")


def cmd_crawl(args):
    """
    Input: args.nickname — target nickname to crawl
    Output: prints dispatched Celery task ID
    Details:
        Looks up the target in MariaDB and dispatches crawl_target.delay().
        The Celery worker processes the task asynchronously.
    """
    _load_env()
    app, db = _get_app()
    with app.app_context():
        target = _lookup_target(db.session, args.nickname)
        from celery_worker.tasks.crawl import crawl_target
        result = crawl_target.delay(target.id)
        print(f"dispatched crawl for '{args.nickname}' (target {target.id})")
        print(f"task id: {result.id}")


def cmd_crawl_all(_args):
    """
    Input: parsed args (unused)
    Output: prints dispatched Celery task ID
    Details:
        Dispatches crawl_all.delay() which fans out to one task per target.
    """
    _load_env()
    from celery_worker.tasks.crawl import crawl_all
    result = crawl_all.delay()
    print(f"dispatched crawl-all")
    print(f"task id: {result.id}")


def cmd_reindex(args):
    """
    Input: args.nickname — target nickname to reindex
    Output: prints dispatched Celery task ID
    Details:
        Looks up the target and dispatches reindex_target.delay().
        Deletes existing OpenSearch docs for the target, then re-crawls.
    """
    _load_env()
    app, db = _get_app()
    with app.app_context():
        target = _lookup_target(db.session, args.nickname)
        from celery_worker.tasks.index import reindex_target
        result = reindex_target.delay(target.id)
        print(f"dispatched reindex for '{args.nickname}' (target {target.id})")
        print(f"task id: {result.id}")


def cmd_reindex_all(args):
    """
    Input: args.yes — skip confirmation prompt
    Output: prints dispatched Celery task ID
    Details:
        Dispatches reindex_all.delay() which wipes the full index then re-crawls
        all targets. Prompts for confirmation unless --yes is passed.
    """
    _load_env()
    if not args.yes:
        answer = input("this will wipe the entire OpenSearch index. continue? [y/N] ")
        if answer.strip().lower() != "y":
            print("aborted")
            return
    from celery_worker.tasks.index import reindex_all
    result = reindex_all.delay()
    print(f"dispatched reindex-all")
    print(f"task id: {result.id}")


def cmd_vectorize(_args):
    """
    Input: parsed args (unused)
    Output: prints dispatched Celery task ID
    Details:
        Dispatches vectorize_pending.delay() to backfill embeddings for all
        documents where vectorized=false.
    """
    _load_env()
    from celery_worker.tasks.vectorize import vectorize_pending
    result = vectorize_pending.delay()
    print(f"dispatched vectorize-pending")
    print(f"task id: {result.id}")


def cmd_create_index(_args):
    """
    Input: parsed args (unused)
    Output: prints result of index creation
    Details:
        Creates the shse_pages OpenSearch index with the full knn_vector schema.
        No-op if the index already exists.
    """
    _load_env()
    from flask_app.services.opensearch import create_index
    try:
        resp = create_index()
        if resp.get("already_exists"):
            print("index already exists — no changes made")
        else:
            print(f"index created: {resp}")
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_wipe_index(args):
    """
    Input: args.yes — skip confirmation prompt
    Output: prints count of deleted documents
    Details:
        Deletes all documents from the shse_pages index. The index structure
        is preserved. Prompts for confirmation unless --yes is passed.
    """
    _load_env()
    if not args.yes:
        answer = input("this will delete ALL documents from the index. continue? [y/N] ")
        if answer.strip().lower() != "y":
            print("aborted")
            return
    from flask_app.services.opensearch import wipe_index
    try:
        resp = wipe_index()
        print(f"deleted {resp.get('deleted', 0):,} documents")
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_search(args):
    """
    Input: args.query — search string
           args.page  — 1-indexed page number (default 1)
           args.limit — results per page (default 10)
    Output: prints ranked BM25 results to stdout
    Details:
        Queries the /api/search endpoint and formats results for the terminal.
        Requires the Flask service to be running (docker compose up).
    """
    _load_env()
    import json
    import urllib.request
    import urllib.parse

    flask_host = os.environ.get("FLASK_HOST", "localhost")
    flask_port = os.environ.get("FLASK_PORT", "5000")
    base = f"http://{flask_host}:{flask_port}"

    params = urllib.parse.urlencode({"q": args.query, "page": args.page})
    url = f"{base}/api/search?{params}"

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        print(f"error: could not reach Flask at {base} — {exc}", file=sys.stderr)
        print("  is the stack running? try: docker compose up -d", file=sys.stderr)
        sys.exit(1)

    total = data.get("total", 0)
    took = data.get("took_ms", 0)
    results = data.get("results", [])
    q = data.get("q", args.query)
    page = data.get("page", 1)
    page_count = data.get("page_count", 1)

    if not results:
        print(f'no results for "{q}"')
        return

    print(f'{total:,} results for "{q}"  ({took}ms)  page {page}/{page_count}')
    print()
    for i, r in enumerate(results, start=1 + (page - 1) * args.limit):
        title = r.get("title", "") or r.get("url", "")
        url_val = r.get("url", "")
        service = r.get("service", "")
        snippet = r.get("snippet", "").strip()
        vectorized = r.get("vectorized", False)
        vec_tag = "" if vectorized else "  [BM25 only]"

        print(f"  [{i}] {title}{vec_tag}")
        if service:
            print(f"      service: {service}")
        print(f"      {url_val}")
        if snippet:
            # wrap snippet at 72 chars
            words = snippet.split()
            line, lines = [], []
            for w in words:
                if sum(len(x) + 1 for x in line) + len(w) > 72:
                    lines.append(" ".join(line))
                    line = [w]
                else:
                    line.append(w)
            if line:
                lines.append(" ".join(line))
            for ln in lines:
                print(f"      {ln}")
        print()

    if page < page_count:
        print(f"  next page: python cli.py search \"{q}\" --page {page + 1}")


def _reset_admin_password_impl(db_session, username, new_password):
    """
    Input: db_session, username str, new_password str
    Output: None (prints success) or raises SystemExit(1) on failure
    Details:
        Queries users for an admin-role row matching username.
        Sets the new bcrypt password and commits. Server-shell access is the
        authorization gate; no current-password check is performed.
    """
    from flask_app.models.user import User
    user = db_session.query(User).filter_by(username=username).first()
    if user is None:
        print(f"error: no user '{username}' found", file=sys.stderr)
        sys.exit(1)
    if user.role != "admin":
        print(f"error: user '{username}' is not an admin (role={user.role!r})", file=sys.stderr)
        sys.exit(1)
    user.set_password(new_password)
    db_session.commit()
    print(f"password updated for admin user '{username}'")


def cmd_reset_admin_password(args):
    """
    Input: args.username — admin username to reset
    Output: prompts for new password; prints success or error
    Details:
        Server-side recovery tool. Does not require the current password.
        Exits non-zero if the user does not exist or is not an admin.
    """
    _load_env()
    pw1 = input("New password: ")
    if not pw1:
        print("error: password cannot be empty", file=sys.stderr)
        sys.exit(1)
    pw2 = input("Confirm password: ")
    if pw1 != pw2:
        print("error: passwords do not match", file=sys.stderr)
        sys.exit(1)
    app, db = _get_app()
    with app.app_context():
        _reset_admin_password_impl(db.session, args.username, pw1)


def cmd_jobs(args):
    """
    Input: args.limit — max rows to show (default 20)
    Output: prints recent CrawlJob rows
    Details:
        Queries MariaDB for the most recent crawl jobs ordered by started_at desc.
    """
    _load_env()
    app, db = _get_app()
    with app.app_context():
        from flask_app.models.crawl_job import CrawlJob
        from flask_app.models.crawler_target import CrawlerTarget
        rows = (
            db.session.query(CrawlJob)
            .order_by(CrawlJob.started_at.desc())
            .limit(args.limit)
            .all()
        )
        if not rows:
            print("no jobs found")
            return
        fmt = "{:<6}  {:<24}  {:<10}  {:<19}  {}"
        print(fmt.format("id", "nickname", "status", "started", "task_id"))
        print("-" * 90)
        target_cache = {}
        for job in rows:
            if job.target_id not in target_cache:
                t = db.session.get(CrawlerTarget, job.target_id)
                target_cache[job.target_id] = t.nickname if t else "(deleted)"
            nickname = target_cache[job.target_id]
            started = str(job.started_at)[:19] if job.started_at else ""
            task_id = (job.task_id or "")[:36]
            print(fmt.format(job.id, (nickname or "")[:24], job.status, started, task_id))


def _build_parser():
    """
    Input: None
    Output: ArgumentParser
    Details:
        Builds the top-level parser and all subcommand parsers.
    """
    p = argparse.ArgumentParser(
        prog="shse",
        description="SHSE admin CLI",
    )
    sub = p.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    sub.add_parser("stats", help="show OpenSearch index stats")

    sub.add_parser("list-targets", help="list all crawler targets")

    up = sub.add_parser("upload-config", help="parse and persist a YAML crawler config")
    up.add_argument("file", metavar="FILE", help="path to YAML config file")

    cr = sub.add_parser("crawl", help="crawl a single target by nickname")
    cr.add_argument("nickname", metavar="NICKNAME")

    sub.add_parser("crawl-all", help="crawl all targets")

    ri = sub.add_parser("reindex", help="delete and re-crawl a single target by nickname")
    ri.add_argument("nickname", metavar="NICKNAME")

    ra = sub.add_parser("reindex-all", help="wipe index and re-crawl all targets")
    ra.add_argument("--yes", action="store_true", help="skip confirmation prompt")

    sub.add_parser("vectorize", help="backfill embeddings for unvectorized documents")

    sub.add_parser("create-index", help="create the OpenSearch index (no-op if exists)")

    wi = sub.add_parser("wipe-index", help="delete all documents from the index")
    wi.add_argument("--yes", action="store_true", help="skip confirmation prompt")

    jb = sub.add_parser("jobs", help="show recent crawl jobs")
    jb.add_argument("--limit", type=int, default=20, metavar="N",
                    help="number of rows to show (default 20)")

    sr = sub.add_parser("search", help="search the index and print results")
    sr.add_argument("query", metavar="QUERY", help="search query string")
    sr.add_argument("--page", type=int, default=1, metavar="N",
                    help="page number (default 1)")
    sr.add_argument("--limit", type=int, default=10, metavar="N",
                    help="results per page (default 10)")

    rap = sub.add_parser("reset-admin-password",
                         help="change an admin user's password (server-side recovery)")
    rap.add_argument("username", metavar="USERNAME", help="admin username to reset")

    return p


_DISPATCH = {
    "stats":          cmd_stats,
    "list-targets":   cmd_list_targets,
    "upload-config":  cmd_upload_config,
    "crawl":          cmd_crawl,
    "crawl-all":      cmd_crawl_all,
    "reindex":        cmd_reindex,
    "reindex-all":    cmd_reindex_all,
    "vectorize":      cmd_vectorize,
    "create-index":   cmd_create_index,
    "wipe-index":     cmd_wipe_index,
    "jobs":                  cmd_jobs,
    "search":                cmd_search,
    "reset-admin-password":  cmd_reset_admin_password,
}


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    _DISPATCH[args.command](args)
