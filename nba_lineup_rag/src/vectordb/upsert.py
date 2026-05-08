"""
upsert.py - Data upsert module

This module is responsible for:
1. Writing chunks into ChromaDB
2. Handling upsert logic (add or update)
3. Batch processing for performance improvement

Upsert vs Add:
- add(): Only adds new records; raises error if ID duplicates
- upsert(): Adds or updates; updates if ID exists, inserts if not

Naming conventions:
- upsert_chunks(): Write a list of DocumentChunk instances
- upsert_batch(): Batch write (for large amount of data)
"""

import numpy as np
from typing import List, Dict, Any, Optional

import chromadb

from src.processing.chunking import DocumentChunk
from src.embeddings import embed_passages
from src.vectordb.collections import get_collection_manager, SOURCE_TO_COLLECTION
from src.logging_utils import get_logger

logger = get_logger(__name__)


def _sanitize_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Clean metadata to ensure all values are compatible with ChromaDB.

    ChromaDB only supports the following metadata types:
    - str
    - int
    - float
    - bool
    - None

    **Lists are NOT supported!**

    This function will:
    1. Convert lists to comma-separated strings
    2. Convert other unsupported types to strings
    3. Remove None values

    Args:
        metadata: Original metadata dictionary

    Returns:
        dict: Cleaned metadata

    Example:
        Original: {"player_names": ["LeBron", "AD"], "team": "LAL"}
        Converted: {"player_names": "LeBron,AD", "team": "LAL"}

    Why "sanitize":
    - "sanitize" means "clean" or "disinfect"
    - Often used in programming to mean "clean/validate input data"
    """
    sanitized = {}

    for key, value in metadata.items():
        # Skip None values
        if value is None:
            continue

        # Convert list type to comma-separated string
        if isinstance(value, list):
            sanitized[key] = ",".join(str(v) for v in value)

        # Convert dict type to JSON string
        elif isinstance(value, dict):
            import json
            sanitized[key] = json.dumps(value, ensure_ascii=False)

        # Keep supported types as is
        elif isinstance(value, (str, int, float, bool)):
            sanitized[key] = value

        # Convert other types to string
        else:
            sanitized[key] = str(value)

    return sanitized


def upsert_chunks(
    chunks: List[DocumentChunk],
    collection_name: str = None,
    embeddings: np.ndarray = None,
) -> int:
    """
    Write chunks to ChromaDB.

    Args:
        chunks: List of DocumentChunk instances
        collection_name: Target collection name.
                         If not specified, will be chosen by chunk's source
        embeddings: Pre-calculated vectors (optional).
                    If not provided, will be computed automatically

    Returns:
        int: Number of chunks written successfully

    Flow:
    1. If no embeddings are provided, compute them
    2. Determine target collection
    3. Perform upsert

    Example usage:
        chunks = chunker.split(text, metadata={...})
        count = upsert_chunks(chunks, collection_name="nba_news")
    """
    if not chunks:
        logger.debug("No chunks to write")
        return 0

    # Compute embeddings if not provided
    if embeddings is None:
        texts = [chunk.text for chunk in chunks]
        logger.info(f"Computing embeddings for {len(texts)} chunks...")
        embeddings = embed_passages(texts)

    # Determine collection
    manager = get_collection_manager()

    if collection_name:
        collection = manager.get_collection(collection_name)
    else:
        # Use source from first chunk to determine collection
        source = chunks[0].metadata.get("source", "unknown")
        collection = manager.get_collection_for_source(source)

    # Prepare data
    ids = [chunk.id for chunk in chunks]
    documents = [chunk.text for chunk in chunks]

    # Sanitize metadata (convert lists to string, as ChromaDB doesn't support lists)
    # This step is critical! Without cleaning, upsert will fail
    metadatas = [_sanitize_metadata(chunk.metadata) for chunk in chunks]

    # Convert numpy array to list (ChromaDB requirement)
    embeddings_list = embeddings.tolist()

    # Perform upsert
    logger.info(f"Upserting {len(chunks)} chunks into {collection.name}")

    try:
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings_list,
        )
        logger.info(f"Successfully wrote {len(chunks)} chunks")
        return len(chunks)

    except Exception as e:
        logger.error(f"Upsert failed: {e}")
        return 0


def upsert_batch(
    chunks: List[DocumentChunk],
    collection_name: str = None,
    batch_size: int = 100,
    compute_embeddings: bool = True,
) -> int:
    """
    Batch write chunks.

    Used for handling large datasets, avoiding loading too many embeddings into memory at once.

    Args:
        chunks: List of DocumentChunk instances
        collection_name: Target collection name
        batch_size: Number of chunks per batch
        compute_embeddings: Whether or not to compute embeddings

    Returns:
        int: Total number of chunks written

    Example usage:
        # Handle lots of documents
        all_chunks = []
        for doc in documents:
            all_chunks.extend(chunker.split(doc))

        total = upsert_batch(all_chunks, batch_size=50)
    """
    if not chunks:
        return 0

    total_count = 0
    total_batches = (len(chunks) + batch_size - 1) // batch_size

    logger.info(f"Batch processing {len(chunks)} chunks ({total_batches} batches)")

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        batch_num = i // batch_size + 1

        logger.debug(f"Processing batch {batch_num}/{total_batches}")

        if compute_embeddings:
            # Embeddings for this batch will be computed in upsert_chunks
            count = upsert_chunks(batch, collection_name)
        else:
            # Assume chunks already have embeddings (uncommon)
            count = upsert_chunks(batch, collection_name)

        total_count += count

    logger.info(f"Batch processing complete, wrote {total_count} chunks in total")
    return total_count


def upsert_from_raw(
    raw_items: List[Dict[str, Any]],
    chunker,
    extractor,
    collection_name: str = None,
) -> int:
    """
    Directly process and write from raw items.

    Integrates the full flow of processing and vectordb writing.

    Args:
        raw_items: List of RawItem dicts
        chunker: TextChunker instance
        extractor: EntityExtractor instance
        collection_name: Target collection

    Returns:
        int: Number of chunks written

    Steps:
    1. Chunk each raw item
    2. Extract entities and add to metadata
    3. Batch write
    """
    all_chunks = []

    for item in raw_items:
        # Prepare base metadata
        metadata = {
            "source": item.get("source"),
            "source_url": item.get("source_url"),
            "published_at": item.get("published_at"),
            "fetched_at": item.get("fetched_at"),
            "title": item.get("title"),
        }

        # Extract entities
        entities = extractor.extract_to_metadata(item.get("raw_text", ""))
        metadata.update(entities)

        # Chunk the text
        chunks = chunker.split(item.get("raw_text", ""), metadata)
        all_chunks.extend(chunks)

    # Batch write
    return upsert_batch(all_chunks, collection_name)


def delete_by_source(source: str, collection_name: str = None) -> int:
    """
    Delete all chunks from a specific source.

    Args:
        source: Source name
        collection_name: Collection name

    Returns:
        int: Number of deletions
    """
    manager = get_collection_manager()

    if collection_name:
        collection = manager.get_collection(collection_name)
    else:
        collection = manager.get_collection_for_source(source)

    # Query all IDs from the source
    # ChromaDB's where filter
    results = collection.get(
        where={"source": source},
        include=[]  # Only need IDs
    )

    ids_to_delete = results.get("ids", [])

    if ids_to_delete:
        collection.delete(ids=ids_to_delete)
        logger.info(f"Deleted {len(ids_to_delete)} chunks (source: {source})")

    return len(ids_to_delete)

