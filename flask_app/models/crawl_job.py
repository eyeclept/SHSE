"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    CrawlJob model. Tracks Celery task state for each crawl or reindex operation.
"""
# Imports
from datetime import datetime
from flask_app import db

# Globals

# Functions
class CrawlJob(db.Model):
    """
    Input: None
    Output: ORM model mapped to the crawl_jobs table
    Details:
        task_id is the Celery async result ID, used to poll job status.
        status mirrors Celery states: queued, started, success, failure.
    """
    __tablename__ = "crawl_jobs"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String(256), unique=True)
    target_id = db.Column(db.Integer, db.ForeignKey("crawler_targets.id"))
    status = db.Column(db.String(64), default="queued")
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)


if __name__ == "__main__":
    pass
