"""
Author: Richard Baldwin
Date:   2024
Email: eyeclept@pm.me

Description: Search routes - BM25 results, optional AI summary, search history
"""


def search_view():
    """
    Input: query (str from request), optional ai_summary flag
    Output: JSON with BM25 results and optional AI summary
    Details: Queries Elasticsearch, saves to search history
    """
    pass


def search_history_view():
    """
    Input: user_id (from session)
    Output: List of past queries with timestamps
    Details: Retrieves from MariaDB search_history table
    """
    pass
