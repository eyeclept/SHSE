"""
Author: Richard Baldwin
Date:   2024
Email: eyeclept@pm.me

Description: Celery task definitions - crawl, index, vectorize
"""

from src.celery_worker import celery_app


@celery_app.task(name='crawl_target')
def crawl_target(target_id):
    """
    Input: target_id (int) - ID of crawler target
    Output: None (result stored in crawl_jobs table)
    Details: Triggers Nutch via REST API, consumes crawled content, chunks (800 tokens),
             calls Ollama for embeddings (if available), indexes to ES
    """
    pass


@celery_app.task(name='crawl_all')
def crawl_all():
    """
    Input: None
    Output: None
    Details: Crawls all targets defined in crawler_targets table
    """
    pass


@celery_app.task(name='reindex_target')
def reindex_target(target_id):
    """
    Input: target_id (int)
    Output: None
    Details: Delete ES docs for target → re-crawl → re-index
    """
    pass


@celery_app.task(name='reindex_all')
def reindex_all():
    """
    Input: None
    Output: None
    Details: Wipe ES index → crawl all targets → index all
    """
    pass


@celery_app.task(name='vectorize_pending')
def vectorize_pending():
    """
    Input: None
    Output: None
    Details: Query ES for vectorized=false docs (paginated), batch through Ollama,
             update with embedding + vectorized=true
    """
    pass


@celery_app.task(name='scheduled_crawl')
def scheduled_crawl(schedule_id):
    """
    Input: schedule_id (int) - ID from crawler config schedule
    Output: None
    Details: Triggered by Celery Beat based on cron-like schedule from YAML config
    """
    pass
