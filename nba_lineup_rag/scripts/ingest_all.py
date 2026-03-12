#!/usr/bin/env python3
"""
ingest_all.py - Main Data Ingestion Script

This script is responsible for:
1. Fetching data from all sources
2. Processing and writing to the raw store
3. Chunking and building vector index

Usage:
    # Fetch data from the last 6 hours
    python scripts/ingest_all.py --since 6h

    # Fetch only from specific sources
    python scripts/ingest_all.py --sources espn_rss,injuries_pages

    # Full fetch (no time limit)
    python scripts/ingest_all.py --full

Naming conventions:
- main(): Main program entry
- ingest_source(): Ingest a single source
- parse_time_window(): Parse time parameter
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
import time

# Add project root to Python path
# So that src modules can be imported correctly
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config import get_config
from src.logging_utils import get_logger, IngestionStats
from src.sources.espn_rss import ESPNRSSFetcher
from src.sources.injuries_pages import InjuriesPageFetcher
from src.processing.normalize import normalize_text
from src.processing.chunking import TextChunker
from src.processing.extract_entities import EntityExtractor
from src.processing.dedupe import Deduplicator
from src.vectordb.collections import get_collection_manager
from src.vectordb.upsert import upsert_chunks

logger = get_logger("ingest_all")


def parse_time_window(time_str: str) -> int:
    """
    Parse time parameter

    Supported formats:
    - "6h" -> 6 hours
    - "30m" -> 30 minutes (converted to hours)
    - "2d" -> 2 days

    Args:
        time_str: Time string, e.g., "6h", "30m", "2d"

    Returns:
        int: Number of hours

    Example:
        hours = parse_time_window("6h")  # returns 6
        hours = parse_time_window("2d")  # returns 48
    """
    time_str = time_str.lower().strip()

    if time_str.endswith("h"):
        return int(time_str[:-1])
    elif time_str.endswith("m"):
        # Minutes to hours (at least 1 hour)
        return max(1, int(time_str[:-1]) // 60)
    elif time_str.endswith("d"):
        return int(time_str[:-1]) * 24
    else:
        # Default is hour
        return int(time_str)


def ingest_espn_rss(since_hours: int = None) -> IngestionStats:
    """
    Fetch and process ESPN RSS

    Args:
        since_hours: Only fetch data within the last X hours

    Returns:
        IngestionStats: Ingestion statistics
    """
    stats = IngestionStats("espn_rss")

    logger.info("=== Starting ESPN RSS Ingestion ===")

    try:
        # 1. Fetch data
        fetcher = ESPNRSSFetcher()
        if since_hours:
            items = fetcher.fetch_since(since_hours)
        else:
            items = fetcher.fetch()

        if not items:
            logger.warning("No new ESPN RSS data")
            return stats

        # 2. Save raw data
        new_count = fetcher.save_raw(items)
        stats.add_new(new_count)
        stats.add_skipped(len(items) - new_count)

        # 3. Process and chunk
        chunker = TextChunker()
        extractor = EntityExtractor()

        all_chunks = []
        for item in items:
            # Normalize text
            text = normalize_text(item["raw_text"])

            # Prepare metadata
            metadata = {
                "source": item["source"],
                "source_url": item["source_url"],
                "published_at": item["published_at"],
                "fetched_at": item["fetched_at"],
                "title": item["title"],
            }

            # Extract entities
            entities = extractor.extract_to_metadata(text)
            metadata.update(entities)

            # Chunk
            chunks = chunker.split(text, metadata)
            all_chunks.extend(chunks)

        stats.add_chunks(len(all_chunks))

        # 4. Write to vector database
        if all_chunks:
            start_time = time.time()
            upsert_chunks(all_chunks, collection_name="nba_news")
            stats.set_embed_time(time.time() - start_time)

        stats.log_summary(logger)
        return stats

    except Exception as e:
        logger.error(f"ESPN RSS ingestion failed: {e}")
        stats.add_error()
        return stats


def ingest_injuries_pages() -> IngestionStats:
    """
    Fetch and process injuries pages

    Returns:
        IngestionStats: Ingestion statistics
    """
    stats = IngestionStats("injuries_pages")

    logger.info("=== Starting Injuries Pages Ingestion ===")

    try:
        # 1. Fetch data
        fetcher = InjuriesPageFetcher()
        injuries_by_source = fetcher.fetch_all()

        if not injuries_by_source:
            logger.warning("No injuries pages data")
            return stats

        # 2. Save raw data
        total_count = fetcher.save_raw(injuries_by_source)
        stats.add_new(total_count)

        # 3. Process and chunk
        # Each chunk is per player
        from src.processing.chunking import DocumentChunk, generate_chunk_id, compute_text_hash
        from datetime import timezone

        all_chunks = []
        now = datetime.now(timezone.utc).isoformat()

        for source, injuries in injuries_by_source.items():
            for injury in injuries:
                text = injury.to_chunk_text()
                chunk_hash = compute_text_hash(text)

                metadata = {
                    "source": f"injuries_pages_{source}",
                    "source_url": (
                        fetcher.config.ESPN_INJURIES_URL if source == "espn"
                        else fetcher.config.CBS_INJURIES_URL
                    ),
                    "published_at": now,
                    "fetched_at": now,
                    "team": injury.team,
                    "player_names": [injury.player_name],
                    "topic": "injury",
                    "injury_status": [injury.status] if injury.status else [],
                    "hash": chunk_hash,
                }

                chunk_id = generate_chunk_id(
                    source=metadata["source"],
                    source_url=metadata["source_url"],
                    published_at=now,
                    chunk_index=0,
                    chunk_hash_prefix=chunk_hash[:8],
                )

                all_chunks.append(DocumentChunk(
                    id=chunk_id,
                    text=text,
                    metadata=metadata,
                ))

        stats.add_chunks(len(all_chunks))

        # 4. Write to vector database
        if all_chunks:
            start_time = time.time()
            upsert_chunks(all_chunks, collection_name="nba_injuries_pages")
            stats.set_embed_time(time.time() - start_time)

        stats.log_summary(logger)
        return stats

    except Exception as e:
        logger.error(f"Injuries pages ingestion failed: {e}")
        stats.add_error()
        return stats


def main():
    """
    Main program entry

    Parse command line arguments and run ingestion
    """
    # Parse command line arguments
    # argparse is Python's standard command line argument parsing module
    parser = argparse.ArgumentParser(
        description="NBA Lineup RAG - Data Ingestion Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage examples:
    # Fetch data from the last 6 hours
    python scripts/ingest_all.py --since 6h

    # Only fetch ESPN RSS
    python scripts/ingest_all.py --sources espn_rss

    # Full ingestion
    python scripts/ingest_all.py --full
        """
    )

    # --since: time window
    parser.add_argument(
        "--since",
        type=str,
        default="6h",
        help="Only fetch data within this period (e.g., 6h, 30m, 2d)"
    )

    # --sources: specify sources
    parser.add_argument(
        "--sources",
        type=str,
        default="espn_rss,injuries_pages",
        help="Sources to fetch, comma-separated (espn_rss,injuries_pages)"
    )

    # --full: full ingestion
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full ingestion, no time limit"
    )

    args = parser.parse_args()

    # Parse time window
    since_hours = None if args.full else parse_time_window(args.since)

    # Parse sources list
    sources = [s.strip() for s in args.sources.split(",")]

    logger.info(f"Starting ingestion - sources: {sources}, time window: {since_hours}h")

    # Ensure collections exist
    get_collection_manager().ensure_all_collections()

    # Ingest
    all_stats = []

    if "espn_rss" in sources:
        stats = ingest_espn_rss(since_hours)
        all_stats.append(stats)

    if "injuries_pages" in sources:
        stats = ingest_injuries_pages()
        all_stats.append(stats)

    # Summary
    logger.info("=== Ingestion completed ===")
    total_new = sum(s.new_count for s in all_stats)
    total_chunks = sum(s.chunks_count for s in all_stats)
    total_errors = sum(s.error_count for s in all_stats)

    logger.info(f"Total: {total_new} new, {total_chunks} chunks, {total_errors} errors")


if __name__ == "__main__":
    main()
