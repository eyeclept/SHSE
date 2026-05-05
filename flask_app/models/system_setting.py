"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    SystemSetting model. Key-value store for admin-configurable runtime settings.
    Rows are written by config_parser.persist_targets() when a YAML config is
    uploaded; read by llm.py at call time with env-var fallback.
"""
# Imports
from flask_app import db

# Globals

# Functions
class SystemSetting(db.Model):
    """
    Input: None
    Output: ORM model mapped to the system_settings table
    Details:
        key   — setting name (e.g. "llm.gen_model"); primary key
        value — setting value as TEXT; None means "use default"
    """
    __tablename__ = "system_settings"

    key = db.Column(db.String(128), primary_key=True)
    value = db.Column(db.Text, nullable=True)


if __name__ == "__main__":
    pass
