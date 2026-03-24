"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    CrawlerTarget model. Stores parsed crawler target configuration.
    Targets are either type 'service' (specific host) or 'network' (subnet scan).
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
    target_type = db.Column(db.Enum("service", "network"), nullable=False)
    url = db.Column(db.String(512))
    ip = db.Column(db.String(64))
    network = db.Column(db.String(64))
    port = db.Column(db.Integer)
    route = db.Column(db.String(256), default="/")
    service = db.Column(db.String(32), default="http")
    tls_verify = db.Column(db.Boolean, default=True)
    schedule_yaml = db.Column(db.Text)
    yaml_source = db.Column(db.Text)

    crawl_jobs = db.relationship("CrawlJob", backref="target", lazy=True)


if __name__ == "__main__":
    pass
