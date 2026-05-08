"""
collections.py - Collection management module

This module is responsible for:
1. Defining configuration for each collection
2. Creating and managing collections
3. Providing a unified interface to access collections

Collection design strategy:
- nba_news: ESPN news (articles)
- nba_injury_reports: Official injury reports
- nba_injuries_pages: List of injury report web pages

Advantages of splitting collections:
1. Allows different top_k for different sources
2. Enables priority querying for more trustworthy sources
3. Facilitates independent updating and rebuilding

Naming notes:
- CollectionManager: The collection manager class
- COLLECTION_NAMES: Predefined collection names
- get_collection(): Fetch a specific collection
"""

import chromadb
from typing import Dict, Optional, List
from dataclasses import dataclass

from src.vectordb.chroma_client import get_chroma_client
from src.logging_utils import get_logger

logger = get_logger(__name__)


# Predefined collection names
# Use constants to avoid typos
COLLECTION_NAMES = {
    "news": "nba_news",
    "injury_reports": "nba_injury_reports",
    "injuries_pages": "nba_injuries_pages",
}

# Mapping from data source to collection
SOURCE_TO_COLLECTION = {
    "espn_rss": "nba_news",
    "nba_injury_report": "nba_injury_reports",
    "injuries_pages_espn": "nba_injuries_pages",
    "injuries_pages_cbs": "nba_injuries_pages",
}


@dataclass
class CollectionConfig:
    """
    Collection configuration

    Field descriptions:
    - name: collection name
    - description: description
    - default_top_k: default number of search results to return
    - priority: query priority (lower number is higher priority)
    """
    name: str
    description: str
    default_top_k: int = 10
    priority: int = 1


# Collection configurations
COLLECTION_CONFIGS = {
    "nba_news": CollectionConfig(
        name="nba_news",
        description="ESPN NBA news articles",
        default_top_k=5,
        priority=3,  # lowest priority
    ),
    "nba_injury_reports": CollectionConfig(
        name="nba_injury_reports",
        description="Official NBA injury reports",
        default_top_k=8,
        priority=1,  # highest priority
    ),
    "nba_injuries_pages": CollectionConfig(
        name="nba_injuries_pages",
        description="ESPN/CBS web injury page",
        default_top_k=6,
        priority=2,
    ),
}


class CollectionManager:
    """
    Collection manager

    Provides unified interface for creating, fetching, and deleting collections

    Example usage:
        manager = CollectionManager()

        # Ensure all collections exist
        manager.ensure_all_collections()

        # Fetch a specific collection
        news_coll = manager.get_collection("nba_news")

        # Query
        results = news_coll.query(query_embeddings=[...], n_results=5)
    """

    def __init__(self, client: chromadb.ClientAPI = None):
        """
        Initialize the manager

        Args:
            client: ChromaDB client. If not specified, uses the global client.
        """
        self.client = client or get_chroma_client()

        # Cache for already fetched collections
        self._collections: Dict[str, chromadb.Collection] = {}

    def get_collection(
        self,
        name: str,
        create_if_missing: bool = True,
    ) -> chromadb.Collection:
        """
        Fetch a collection

        Args:
            name: Collection name
            create_if_missing: If missing, create the collection

        Returns:
            chromadb.Collection: The Collection object

        Main methods of a Collection object:
        - add(): Add documents
        - upsert(): Insert or update documents
        - query(): Query
        - get(): Fetch by ID
        - delete(): Delete
        - count(): Count documents
        """
        # Check cache
        if name in self._collections:
            return self._collections[name]

        if create_if_missing:
            # get_or_create_collection: get if exists; otherwise create
            collection = self.client.get_or_create_collection(
                name=name,
                metadata={
                    "description": COLLECTION_CONFIGS.get(name, CollectionConfig(name=name, description="")).description,
                    "hnsw:space": "cosine",  # use cosine similarity
                }
            )
        else:
            # get_collection: raises if doesn't exist
            collection = self.client.get_collection(name)

        # Add to cache
        self._collections[name] = collection

        logger.debug(f"Fetched collection: {name} (count: {collection.count()})")
        return collection

    def ensure_all_collections(self):
        """
        Ensure all predefined collections exist

        Call during application startup to ensure database schema completeness
        """
        for config in COLLECTION_CONFIGS.values():
            self.get_collection(config.name, create_if_missing=True)

        logger.info(f"Ensured {len(COLLECTION_CONFIGS)} collections exist")

    def delete_collection(self, name: str):
        """
        Delete a collection

        Args:
            name: Collection name
        """
        try:
            self.client.delete_collection(name)
            if name in self._collections:
                del self._collections[name]
            logger.info(f"Deleted collection: {name}")
        except Exception as e:
            logger.warning(f"Failed to delete collection: {name} - {e}")

    def reset_collection(self, name: str):
        """
        Reset a collection (delete and recreate)

        Args:
            name: Collection name
        """
        self.delete_collection(name)
        self.get_collection(name, create_if_missing=True)
        logger.info(f"Reset collection: {name}")

    def get_collection_for_source(self, source: str) -> chromadb.Collection:
        """
        Fetch the collection for a given data source

        Args:
            source: Data source name (e.g., 'espn_rss')

        Returns:
            chromadb.Collection: The corresponding collection

        Example usage:
            coll = manager.get_collection_for_source("espn_rss")
            # Returns the nba_news collection
        """
        collection_name = SOURCE_TO_COLLECTION.get(source)

        if not collection_name:
            # Unknown source; use default news collection
            logger.warning(f"Unknown source {source}; using nba_news")
            collection_name = "nba_news"

        return self.get_collection(collection_name)

    def get_stats(self) -> Dict[str, dict]:
        """
        Get statistics about all collections

        Returns:
            dict: {collection_name: {count: int, ...}}
        """
        stats = {}

        for name in COLLECTION_CONFIGS:
            try:
                coll = self.get_collection(name, create_if_missing=False)
                stats[name] = {
                    "count": coll.count(),
                    "priority": COLLECTION_CONFIGS[name].priority,
                }
            except Exception:
                stats[name] = {"count": 0, "exists": False}

        return stats

    def list_collections(self) -> List[str]:
        """
        List all existing collections

        Returns:
            List[str]: List of collection names
        """
        collections = self.client.list_collections()
        return [c.name for c in collections]


# Global manager
_manager: Optional[CollectionManager] = None


def get_collection_manager() -> CollectionManager:
    """
    Get the global CollectionManager

    Returns:
        CollectionManager: manager instance
    """
    global _manager
    if _manager is None:
        _manager = CollectionManager()
    return _manager


def get_collection(name: str) -> chromadb.Collection:
    """
    Convenience function: fetch a collection

    Args:
        name: Collection name

    Returns:
        chromadb.Collection: The Collection object

    Example:
        from src.vectordb import get_collection

        news = get_collection("nba_news")
        results = news.query(...)
    """
    return get_collection_manager().get_collection(name)

