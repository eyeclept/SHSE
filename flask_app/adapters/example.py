"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Example api-push adapter. Copy this file and rename it to match the
    `adapter` field on your CrawlerTarget row (e.g. discourse_adapter.py).
    Implement fetch() to pull content from your service's API.

    The adapter receives a CrawlerTarget ORM object so it can read
    target.url, target.nickname, and any custom fields.

Usage in crawler config YAML:
    - type: api-push
      nickname: my-service
      url: http://my-service.lab.internal
      adapter: example          # → flask_app/adapters/example.py
"""
# Imports

# Globals

# Functions
def fetch(target):
    """
    Input:  target - CrawlerTarget ORM object
    Output: list of {url, title, text} dicts to index in OpenSearch
    Details:
        Replace this implementation with real API calls to your service.
        Return an empty list to index nothing (e.g. if the API is unreachable).
        Raise exceptions only for unrecoverable errors — the Celery task
        will catch them and set the CrawlJob status to 'failure'.
    """
    # Example: fetch from a hypothetical /api/content endpoint
    # import requests
    # resp = requests.get(f"{target.url}/api/content", timeout=15)
    # resp.raise_for_status()
    # items = resp.json()
    # return [{"url": i["url"], "title": i["title"], "text": i["body"]} for i in items]
    return []
