"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    CrawlerTarget model. Stores parsed crawler target configuration.
    Target types: service (Nutch crawl), network (subnet scan), oai-pmh (Metha
    harvest), feed (RSS/Atom/ActivityPub), api-push (custom adapter).
"""
# Imports
from flask_app import db

# Globals

# Functions
class CrawlerTarget(db.Model):
    """
    Input: None
    Output: ORM model mapped to the crawler_targets table
    Details:
        yaml_source stores the raw YAML blob uploaded by the admin.
        schedule_yaml stores the resolved schedule block for this target.
    """
    __tablename__ = "crawler_targets"

    id = db.Column(db.Integer, primary_key=True)
    nickname = db.Column(db.String(128))
    target_type = db.Column(
        db.Enum("service", "network", "oai-pmh", "feed", "api-push"),
        nullable=False,
    )
    url = db.Column(db.String(512))
    ip = db.Column(db.String(64))
    network = db.Column(db.String(64))
    port = db.Column(db.Integer)
    route = db.Column(db.String(256), default="/")
    service = db.Column(db.String(32), default="http")
    tls_verify = db.Column(db.Boolean, default=True)
    endpoint = db.Column(db.String(256))   # oai-pmh OAI endpoint path
    feed_path = db.Column(db.String(256))  # feed RSS/Atom path
    adapter = db.Column(db.String(256))    # api-push adapter script name
    crawl_depth = db.Column(db.Integer, default=2)  # BFS max_depth for service/network targets
    schedule_yaml = db.Column(db.Text)
    yaml_source = db.Column(db.Text)

    crawl_jobs = db.relationship("CrawlJob", backref="target", lazy=True)


if __name__ == "__main__":
    pass
