"""
Author: Richard Baldwin
Date:   2024
Email: eyeclept@pm.me

Description: Text chunking utilities for document processing
"""


def chunk_text(text, chunk_size=800, overlap=100):
    """
    Input: text (str), chunk_size (int) - tokens per chunk, overlap (int) - overlap between chunks
    Output: list[str] - text chunks
    Details: Splits text into chunks of ~800 tokens with optional overlap
    """
    pass


def chunk_documents(documents, chunk_size=800, overlap=100):
    """
    Input: documents (list[dict]) - crawled pages with 'text' field
    Output: list[dict] - documents with 'chunks' field containing list of chunks
    Details: Chunks multiple documents, preserving metadata (url, title, etc.)
    """
    pass
