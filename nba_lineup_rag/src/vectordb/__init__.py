"""
vectordb - ChromaDB vector database module

This package is responsible for vector database operations:
- chroma_client: ChromaDB client management
- collections: Collection creation and management
- upsert: Data writing (insert/update)
- query: Semantic querying

ChromaDB Overview:
- Lightweight vector database
- Supports persistent storage
- Built-in metadata filtering
- Suitable for small to medium scale applications
"""

from .chroma_client import get_chroma_client, ChromaClientManager
from .collections import CollectionManager, COLLECTION_NAMES
from .upsert import upsert_chunks, upsert_batch
from .query import QueryEngine, query_collection

__all__ = [
    "get_chroma_client",
    "ChromaClientManager",
    "CollectionManager",
    "COLLECTION_NAMES",
    "upsert_chunks",
    "upsert_batch",
    "QueryEngine",
    "query_collection",
]

