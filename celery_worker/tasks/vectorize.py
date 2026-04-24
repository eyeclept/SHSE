"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Vectorize task. Backfills embeddings for documents that were indexed
    without a vector (vectorized=false) because the LLM API was unavailable at
    index time.
"""
# Imports
from celery_worker.app import celery

# Globals

# Functions
@celery.task
def vectorize_pending():
    """
    Input: None
    Output: None
    Details:
        Paginates through OpenSearch docs where vectorized=false.
        Batches text chunks through the LLM API embedding endpoint.
        Updates each doc with the resulting embedding and sets vectorized=true.
    """
    pass


if __name__ == "__main__":
    pass
