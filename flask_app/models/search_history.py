"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    SearchHistory model. Records each query a user submits with a timestamp.
"""
# Imports
from datetime import datetime
from flask_app import db

# Globals

# Functions
class SearchHistory(db.Model):
    """
    Input: None
    Output: ORM model mapped to the search_history table
    Details:
        Linked to a user via user_id foreign key.
        timestamp defaults to UTC at insert time.
    """
    __tablename__ = "search_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    query = db.Column(db.String(512), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


if __name__ == "__main__":
    pass
