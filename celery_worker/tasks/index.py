"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Index tasks. Chunks crawled content at 800 tokens and writes documents
    to OpenSearch. Embedding is deferred (vectorized=false) when the LLM API
    is unavailable.
"""
# Imports
from celery_worker.app import celery

# Globals

# Functions
@celery.task
def reindex_target(target_id):
    """
    Input: target_id (int) — ID of a CrawlerTarget row
    Output: None
    Details:
        Deletes all OpenSearch documents for the target, re-crawls via Nutch,
        then re-indexes the fresh content.
    """
    pass


@celery.task
def reindex_all():
    """
    Input: None
    Output: None
    Details:
        Wipes the entire OpenSearch index then rebuilds from all targets.
    """
    pass


if __name__ == "__main__":
    pass
