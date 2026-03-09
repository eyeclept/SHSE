"""
Author: Richard Baldwin
Date:   2024
Email: eyeclept@pm.me

Description: SQLAlchemy ORM models for MariaDB tables
"""


class User:
    """
    Input: None
    Output: None
    Details: Table: users
             Fields: id, username, password_hash, role (admin/user), sso_identity, created_at
    """
    pass


class SearchHistory:
    """
    Input: None
    Output: None
    Details: Table: search_history
             Fields: id, user_id, query, timestamp
    """
    pass


class CrawlerTarget:
    """
    Input: None
    Output: None
    Details: Table: crawler_targets
             Fields: id, yaml_source (blob), parsed config (service_name, url, port, etc.)
    """
    pass


class CrawlJob:
    """
    Input: None
    Output: None
    Details: Table: crawl_jobs
             Fields: id, task_id, target_id, status, started_at, finished_at
    """
    pass
