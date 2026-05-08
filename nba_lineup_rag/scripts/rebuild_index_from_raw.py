#!/usr/bin/env python3
"""
rebuild_index_from_raw.py - Rebuild Index from Raw Script

This script is responsible for:
1. Reading all data from the raw store
2. Reprocessing (normalize, chunk, extract entities)
3. Rebuilding the vector index

Use cases:
- Changed chunk_size setting
- Changed entity extraction logic
- Swapped out embedding model
- Vector database needs to be rebuilt due to corruption

Usage:
    # Rebuild all collections
    python scripts/rebuild_index_from_raw.py

    # Only rebuild a specific source
    python scripts/rebuild_index_from_raw.py --source espn_rss

Naming conventions:
- main(): Program entry point
- rebuild_from_source(): Rebuild from the raw data of a specific source
- load_raw_files(): Load raw JSONL files
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
import time

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config import get_config
from src.logging_utils import get_logger, IngestionStats
from src.processing.normalize import normalize_text
from src.processing.chunking import TextChunker, DocumentChunk, generate_chunk_id, compute_text_hash
from src.processing.extract_entities import EntityExtractor
from src.vectordb.collections import get_collection_manager
from src.vectordb.upsert import upsert_batch

logger = get_logger("rebuild_index")


def load_raw_files(raw_dir: Path) -> list:
    """
    Load all JSONL files under the raw directory

    Args:
        raw_dir: Raw data directory

    Returns:
        list: List of RawItems
    """
    items = []

    if not raw_dir.exists():
        logger.warning(f"Raw directory does not exist: {raw_dir}")
        return items

    # Traverse all JSONL files (recursively search subdirectories with rglob)
    for jsonl_file in raw_dir.rglob("*.jsonl"):
        logger.info(f"Loading: {jsonl_file}")

        try:
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        item = json.loads(line.strip())
                        items.append(item)
                    except json.JSONDecodeError as e:
                        logger.warning(f"{jsonl_file}:{line_num} JSON decode failed: {e}")
        except Exception as e:
            logger.error(f"Failed to read file: {jsonl_file} - {e}")

    logger.info(f"Loaded {len(items)} raw records in total")
    return items


def rebuild_news(items: list) -> IngestionStats:
    """
    Rebuild the ESPN news index

    Args:
        items: Raw items from espn_rss

    Returns:
        IngestionStats: Processing statistics
    """
    stats = IngestionStats("rebuild_news")

    if not items:
        return stats

    chunker = TextChunker()
    extractor = EntityExtractor()

    all_chunks = []

    for item in items:
        try:
            # Normalize text
            text = normalize_text(item.get("raw_text", ""))
            if not text:
                stats.add_skipped()
                continue

            # Prepare metadata
            metadata = {
                "source": item.get("source", "espn_rss"),
                "source_url": item.get("source_url", ""),
                "published_at": item.get("published_at", ""),
                "fetched_at": item.get("fetched_at", ""),
                "title": item.get("title", ""),
            }

            # Extract entities
            entities = extractor.extract_to_metadata(text)
            metadata.update(entities)

            # Chunk
            chunks = chunker.split(text, metadata)
            all_chunks.extend(chunks)
            stats.add_new()

        except Exception as e:
            logger.warning(f"Processing failed: {e}")
            stats.add_error()

    stats.add_chunks(len(all_chunks))

    # Write to vector database
    if all_chunks:
        start_time = time.time()
        upsert_batch(all_chunks, collection_name="nba_news")
        stats.set_embed_time(time.time() - start_time)

    return stats


def rebuild_injuries(items: list) -> IngestionStats:
    """
    Rebuild injury data index

    Args:
        items: Raw items from injuries_pages

    Returns:
        IngestionStats: Processing statistics
    """
    stats = IngestionStats("rebuild_injuries")

    if not items:
        return stats

    all_chunks = []

    for item in items:
        try:
            text = item.get("raw_text", "")
            if not text:
                stats.add_skipped()
                continue

            # Injury data is already one chunk per player
            chunk_hash = compute_text_hash(text)

            metadata = {
                "source": item.get("source", "injuries_pages"),
                "source_url": item.get("source_url", ""),
                "published_at": item.get("published_at", ""),
                "fetched_at": item.get("fetched_at", ""),
                "hash": chunk_hash,
            }

            # If there is structured data
            player_data = item.get("player_data", {})
            if player_data:
                metadata["team"] = player_data.get("team", "")
                metadata["player_names"] = [player_data.get("player_name", "")]
                metadata["topic"] = "injury"
                if player_data.get("status"):
                    metadata["injury_status"] = [player_data.get("status")]

            chunk_id = generate_chunk_id(
                source=metadata["source"],
                source_url=metadata["source_url"],
                published_at=metadata["published_at"],
                chunk_index=0,
                chunk_hash_prefix=chunk_hash[:8],
            )

            all_chunks.append(DocumentChunk(
                id=chunk_id,
                text=text,
                metadata=metadata,
            ))
            stats.add_new()

        except Exception as e:
            logger.warning(f"Processing failed: {e}")
            stats.add_error()

    stats.add_chunks(len(all_chunks))

    # Write to vector database
    if all_chunks:
        start_time = time.time()
        upsert_batch(all_chunks, collection_name="nba_injuries_pages")
        stats.set_embed_time(time.time() - start_time)

    return stats


def main():
    """
    Program entry point
    """
    parser = argparse.ArgumentParser(
        description="Rebuild vector index from raw data",
    )

    parser.add_argument(
        "--source",
        type=str,
        choices=["espn_rss", "injuries_pages", "all"],
        default="all",
        help="Which source to rebuild"
    )

    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear collections before rebuilding"
    )

    args = parser.parse_args()

    config = get_config()
    manager = get_collection_manager()

    logger.info("=== Starting index rebuild ===")

    # Clear collections (if needed)
    if args.reset:
        logger.warning("Clearing existing collections ...")
        if args.source in ["espn_rss", "all"]:
            manager.reset_collection("nba_news")
        if args.source in ["injuries_pages", "all"]:
            manager.reset_collection("nba_injuries_pages")

    # Ensure collections exist
    manager.ensure_all_collections()

    all_stats = []

    # Rebuild ESPN RSS
    if args.source in ["espn_rss", "all"]:
        logger.info("=== Rebuilding ESPN RSS index ===")
        raw_dir = Path(config.raw_dir) / "espn_rss"
        items = load_raw_files(raw_dir)
        stats = rebuild_news(items)
        stats.log_summary(logger)
        all_stats.append(stats)

    # Rebuild injury data
    if args.source in ["injuries_pages", "all"]:
        logger.info("=== Rebuilding injury data index ===")
        raw_dir = Path(config.raw_dir) / "injuries_pages"
        items = load_raw_files(raw_dir)
        stats = rebuild_injuries(items)
        stats.log_summary(logger)
        all_stats.append(stats)

    # Summary
    logger.info("=== Rebuild completed ===")
    total_new = sum(s.new_count for s in all_stats)
    total_chunks = sum(s.chunks_count for s in all_stats)
    logger.info(f"Total: processed {total_new} items, generated {total_chunks} chunks")

    # Show collection statistics
    stats = manager.get_stats()
    for name, info in stats.items():
        logger.info(f"  {name}: {info.get('count', 0)} chunks")


if __name__ == "__main__":
    main()

