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
celery = Celery(
    "shse",
    broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    include=[
        "celery_worker.tasks.crawl",
        "celery_worker.tasks.index",
        "celery_worker.tasks.vectorize",
    ],
)

# Functions
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
