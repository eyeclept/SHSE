"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Crawl tasks. Trigger Apache Nutch crawls via REST API and hand
    crawled content to the index pipeline.
"""
# Imports
from celery_worker.app import celery

# Globals

# Functions
@celery.task
def crawl_target(target_id):
    """
    Input: target_id (int) — ID of a CrawlerTarget row
    Output: None
    Details:
        Fetches target config from MariaDB, triggers a Nutch crawl for that
        target's seed URLs, then pipes crawled content to the index pipeline.
    """
    pass


@celery.task
def crawl_all():
    """
    Input: None
    Output: None
    Details:
        Iterates all active CrawlerTargets and dispatches crawl_target for each.
    """
    pass


@celery.task
def scheduled_crawl():
    """
    Input: None
    Output: None
    Details:
        Invoked by Celery Beat according to the per-target schedules
        defined in the YAML crawler config.
    """
    pass


if __name__ == "__main__":
    pass
