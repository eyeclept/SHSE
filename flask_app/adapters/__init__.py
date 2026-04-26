"""
Adapter package for api-push crawler targets.

Each adapter module must expose a single function:

    def fetch(target) -> list[dict]:
        ...

Where target is a CrawlerTarget ORM object and each returned dict has:
    url   - str, canonical URL for the document
    title - str, document title
    text  - str, plain text content for indexing

The module name must match the `adapter` field on the CrawlerTarget row.
Example: adapter="discourse_adapter" → flask_app/adapters/discourse_adapter.py
"""
