"""
query.py - Query module

This module handles:
1. Semantic search execution
2. Multi-collection joint querying
3. Result sorting and filtering

Query strategy:
1. Query injury_reports first (most credible)
2. Then query injuries_pages (supplement)
3. Finally query news (background info)
4. Merge, deduplicate, and sort

Naming conventions:
- QueryEngine: Query engine class
- query_collection(): Query a single collection
- multi_collection_query(): Multi-collection joint query
"""

import numpy as np
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

import chromadb

from src.embeddings import embed_query
from src.vectordb.collections import (
    get_collection_manager,
    COLLECTION_CONFIGS,
    CollectionConfig,
)
from src.logging_utils import get_logger

logger = get_logger(__name__)


@dataclass
class QueryResult:
    """
    Single query result

    Field descriptions:
    - id: Chunk ID
    - text: Chunk text content
    - metadata: Related metadata
    - distance: Distance to query (smaller is more similar)
    - score: Similarity score (higher is more similar)
    - collection: Source collection
    """
    id: str
    text: str
    metadata: Dict[str, Any]
    distance: float
    score: float
    collection: str = ""
    
    def to_dict(self) -> dict:
        """Convert to dict"""
        return {
            "id": self.id,
            "text": self.text,
            "metadata": self.metadata,
            "distance": self.distance,
            "score": self.score,
            "collection": self.collection,
        }


@dataclass
class QueryInput:
    """
    Query input parameters

    Field descriptions:
    - question: Query question (required)
    - team: Team filter (optional)
    - player: Player filter (optional)
    - game_date: Game date filter (optional)
    - time_window_hours: Time window (hours)
    - top_k: Number of results returned
    """
    question: str
    team: Optional[str] = None
    player: Optional[str] = None
    game_date: Optional[str] = None
    time_window_hours: int = 48
    top_k: int = 10


class QueryEngine:
    """
    Query Engine

    Provides a unified query interface supporting:
    - Single collection query
    - Multi-collection joint query
    - Metadata filtering
    - Result sorting

    Usage example:
        engine = QueryEngine()

        results = engine.query(
            question="Is LeBron playing tonight?",
            team="LAL",
            top_k=10
        )

        for r in results:
            print(f"{r.score:.3f}: {r.text[:100]}")
    """
    
    def __init__(self):
        """Initialize the query engine"""
        self.collection_manager = get_collection_manager()
    
    def query(
        self,
        question: str,
        team: str = None,
        player: str = None,
        game_date: str = None,
        top_k: int = 10,
        collections: List[str] = None,
    ) -> List[QueryResult]:
        """
        Execute query

        Args:
            question: Query question
            team: Team filter
            player: Player filter
            game_date: Date filter
            top_k: Number of results to return
            collections: Collections to search (if None, search all)

        Returns:
            List[QueryResult]: Sorted query results

        Example usage:
            results = engine.query(
                "Will Anthony Davis play tomorrow?",
                team="LAL",
                top_k=5
            )
        """
        # Compute query embedding
        query_embedding = embed_query(question)
        
        # Build metadata filter
        where_filter = self._build_where_filter(team, game_date)
        
        # Decide which collections to query
        if collections is None:
            collections = list(COLLECTION_CONFIGS.keys())
        
        # Query each collection
        all_results = []
        
        for coll_name in collections:
            try:
                config = COLLECTION_CONFIGS.get(coll_name)
                coll_top_k = config.default_top_k if config else top_k
                
                results = self._query_single_collection(
                    collection_name=coll_name,
                    query_embedding=query_embedding,
                    where_filter=where_filter,
                    top_k=coll_top_k,
                )
                
                all_results.extend(results)
                
            except Exception as e:
                logger.warning(f"Query {coll_name} failed: {e}")
        
        # Merge, deduplicate, sort
        merged = self._merge_results(all_results, top_k)
        
        # Player filtering (more flexible to filter after merge using Python)
        if player:
            merged = self._filter_by_player(merged, player)
        
        logger.info(f"Query complete: '{question[:30]}...' -> {len(merged)} results")
        return merged
    
    def _query_single_collection(
        self,
        collection_name: str,
        query_embedding: np.ndarray,
        where_filter: Dict = None,
        top_k: int = 10,
    ) -> List[QueryResult]:
        """
        Query a single collection

        Args:
            collection_name: Collection name
            query_embedding: Query vector
            where_filter: Metadata filter
            top_k: Number of results to return

        Returns:
            List[QueryResult]: Query results
        """
        collection = self.collection_manager.get_collection(collection_name)
        
        # Perform query
        # ChromaDB query method:
        # - query_embeddings: query vector
        # - n_results: number of results
        # - where: metadata filter
        # - include: fields to return
        try:
            results = collection.query(
                query_embeddings=[query_embedding.tolist()],
                n_results=top_k,
                where=where_filter if where_filter else None,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            logger.warning(f"Collection {collection_name} query failed: {e}")
            return []
        
        # Convert to QueryResult
        query_results = []
        
        # results structure:
        # {
        #   'ids': [['id1', 'id2', ...]],
        #   'documents': [['doc1', 'doc2', ...]],
        #   'metadatas': [[{...}, {...}, ...]],
        #   'distances': [[0.1, 0.2, ...]]
        # }
        
        if not results["ids"] or not results["ids"][0]:
            return []
        
        ids = results["ids"][0]
        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]
        
        for i, id_ in enumerate(ids):
            # ChromaDB uses L2 distance, convert to similarity score
            # Smaller distance means more similar, score = 1 / (1 + distance)
            distance = distances[i]
            score = 1 / (1 + distance)
            
            query_results.append(QueryResult(
                id=id_,
                text=documents[i],
                metadata=metadatas[i],
                distance=distance,
                score=score,
                collection=collection_name,
            ))
        
        return query_results
    
    def _build_where_filter(
        self,
        team: str = None,
        game_date: str = None,
    ) -> Optional[Dict]:
        """
        Build metadata filter

        ChromaDB where syntax:
        - Simple condition: {"field": "value"}
        - Multiple AND: {"$and": [{...}, {...}]}
        - Multiple OR: {"$or": [{...}, {...}]}

        Args:
            team: Team code
            game_date: Date

        Returns:
            dict | None: Filter conditions
        """
        conditions = []
        
        if team:
            conditions.append({"team": team})
        
        if game_date:
            conditions.append({"game_date": game_date})
        
        if not conditions:
            return None
        
        if len(conditions) == 1:
            return conditions[0]
        
        return {"$and": conditions}
    
    def _merge_results(
        self,
        results: List[QueryResult],
        top_k: int,
    ) -> List[QueryResult]:
        """
        Merge and deduplicate results

        Deduplication strategy:
        1. Keep only the result with highest score for the same ID
        2. Keep only the result with highest score for the same URL
        3. Sort by score and collection priority

        Args:
            results: All query results
            top_k: Final number of results to return

        Returns:
            List[QueryResult]: Merged results
        """
        if not results:
            return []
        
        # Deduplicate by ID, keep the highest score
        id_to_result: Dict[str, QueryResult] = {}
        
        for r in results:
            if r.id not in id_to_result or r.score > id_to_result[r.id].score:
                id_to_result[r.id] = r
        
        unique_results = list(id_to_result.values())
        
        # Deduplicate by URL (optional, since an article may have multiple chunks)
        url_seen = set()
        deduped = []
        
        for r in unique_results:
            url = r.metadata.get("source_url", "")
            # Only deduplicate news URLs, keep all injury reports
            if "news" in r.collection and url in url_seen:
                continue
            if url:
                url_seen.add(url)
            deduped.append(r)
        
        # Sort: score + collection priority
        def sort_key(r: QueryResult) -> tuple:
            # Get collection priority
            config = COLLECTION_CONFIGS.get(r.collection)
            priority = config.priority if config else 99
            
            # Return (priority, -score) so high-priority comes first
            return (priority, -r.score)
        
        deduped.sort(key=sort_key)
        
        return deduped[:top_k]
    
    def _filter_by_player(
        self,
        results: List[QueryResult],
        player: str,
    ) -> List[QueryResult]:
        """
        Filter results by player name

        Since ChromaDB's metadata filtering for array types is limited,
        we do more flexible filtering in Python here.

        Args:
            results: Query results
            player: Player name

        Returns:
            List[QueryResult]: Filtered results
        """
        player_lower = player.lower()
        filtered = []
        
        for r in results:
            # Check player_names in metadata
            player_names = r.metadata.get("player_names", [])
            if any(player_lower in p.lower() for p in player_names):
                filtered.append(r)
                continue
            
            # Check in text content
            if player_lower in r.text.lower():
                filtered.append(r)
        
        return filtered


def query_collection(
    question: str,
    collection_name: str,
    top_k: int = 10,
    where: Dict = None,
) -> List[QueryResult]:
    """
    Convenience function: query a single collection

    Args:
        question: Query question
        collection_name: Collection name
        top_k: Number of results to return
        where: Metadata filter

    Returns:
        List[QueryResult]: Query results

    Example usage:
        from src.vectordb import query_collection

        results = query_collection(
            "Lakers injury update",
            "nba_injuries_pages",
            top_k=5
        )
    """
    engine = QueryEngine()
    return engine.query(
        question=question,
        top_k=top_k,
        collections=[collection_name],
    )


def search(
    question: str,
    team: str = None,
    player: str = None,
    top_k: int = 10,
) -> List[QueryResult]:
    """
    Convenience function: multi-collection search

    Args:
        question: Query question
        team: Team filter
        player: Player filter
        top_k: Number of results to return

    Returns:
        List[QueryResult]: Search results

    Example usage:
        from src.vectordb.query import search

        results = search(
            "Is LeBron playing tonight?",
            team="LAL",
            top_k=10
        )
    """
    engine = QueryEngine()
    return engine.query(
        question=question,
        team=team,
        player=player,
        top_k=top_k,
    )

