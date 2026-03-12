"""
chroma_client.py - ChromaDB Client Management Module

This module is responsible for:
1. Creating and managing ChromaDB connections
2. Providing a persistent PersistentClient
3. Handling the connection lifecycle

ChromaDB client types:
- Client(): In-memory temporary client (data disappears on restart)
- PersistentClient(path): Persistent client (data is stored on disk)

Naming:
- ChromaClientManager: Client management class
- get_chroma_client(): Get singleton client
"""

import chromadb
from chromadb.config import Settings
from typing import Optional
from pathlib import Path

from src.config import get_config
from src.logging_utils import get_logger

logger = get_logger(__name__)


class ChromaClientManager:
    """
    ChromaDB Client Manager

    Uses PersistentClient to ensure data is stored persistently.

    Example usage:
        manager = ChromaClientManager()
        client = manager.get_client()

        # List all collections
        collections = client.list_collections()

        # Get specific collection
        collection = client.get_or_create_collection("nba_news")
    """

    def __init__(self, chroma_dir: str = None):
        """
        Initialize client manager

        Args:
            chroma_dir: path to ChromaDB data directory.
                        If not specified, will be read from config.
        """
        config = get_config()
        self.chroma_dir = chroma_dir or config.chroma_dir

        # Ensure the directory exists
        Path(self.chroma_dir).mkdir(parents=True, exist_ok=True)

        self._client: Optional[chromadb.ClientAPI] = None

    def get_client(self) -> chromadb.ClientAPI:
        """
        Get the ChromaDB client

        Uses lazy loading: only creates the connection when called for the first time.

        Returns:
            chromadb.ClientAPI: ChromaDB client instance

        Details:
        - PersistentClient will create an SQLite database in the specified directory.
        - Data is automatically persisted and survives restarts.
        - The client is thread-safe.
        """
        if self._client is None:
            logger.info(f"Connecting to ChromaDB: {self.chroma_dir}")

            # Create PersistentClient
            # path: storage directory
            # Settings: extra settings (e.g., anonymous telemetry)
            self._client = chromadb.PersistentClient(
                path=self.chroma_dir,
                settings=Settings(
                    anonymized_telemetry=False,  # Disable anonymous telemetry
                )
            )

            logger.info("Successfully connected to ChromaDB")

        return self._client

    def reset(self):
        """
        Reset the database (delete all data)

        WARNING: This will delete all collections and their data!

        Usage scenarios:
        - Clean up test environment
        - Completely rebuild index
        """
        client = self.get_client()

        # List and delete all collections
        collections = client.list_collections()
        for collection in collections:
            logger.warning(f"Deleting collection: {collection.name}")
            client.delete_collection(collection.name)

        logger.info("ChromaDB has been reset")

    def get_stats(self) -> dict:
        """
        Get database statistics

        Returns:
            dict: Stats for each collection
        """
        client = self.get_client()
        collections = client.list_collections()

        stats = {
            "total_collections": len(collections),
            "collections": {}
        }

        for collection in collections:
            coll = client.get_collection(collection.name)
            stats["collections"][collection.name] = {
                "count": coll.count(),
            }

        return stats


# Global client manager (singleton)
_manager: Optional[ChromaClientManager] = None


def get_chroma_client() -> chromadb.ClientAPI:
    """
    Get the global ChromaDB client

    This is the most common entry point, using a singleton to ensure the entire app uses the same connection.

    Returns:
        chromadb.ClientAPI: ChromaDB client

    Example usage:
        from src.vectordb import get_chroma_client

        client = get_chroma_client()
        collection = client.get_collection("nba_news")
        results = collection.query(query_embeddings=[...], n_results=5)
    """
    global _manager
    if _manager is None:
        _manager = ChromaClientManager()
    return _manager.get_client()


def get_client_manager() -> ChromaClientManager:
    """
    Get the global client manager

    For scenarios needing management features (such as reset, statistics).

    Returns:
        ChromaClientManager: manager instance
    """
    global _manager
    if _manager is None:
        _manager = ChromaClientManager()
    return _manager

