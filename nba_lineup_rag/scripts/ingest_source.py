#!/usr/bin/env python3
"""
ingest_source.py - Single Source Fetch Script

This script is used to test or debug a single data source.

Usage:
    python scripts/ingest_source.py --source espn_rss
    python scripts/ingest_source.py --source injuries_pages --save
"""

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.logging_utils import get_logger
from src.sources.espn_rss import ESPNRSSFetcher
from src.sources.injuries_pages import InjuriesPageFetcher

logger = get_logger("ingest_source")


def main():
    parser = argparse.ArgumentParser(description="Single source fetch test")
    
    parser.add_argument(
        "--source",
        type=str,
        required=True,
        choices=["espn_rss", "injuries_pages"],
        help="Source to fetch"
    )
    
    parser.add_argument(
        "--save",
        action="store_true",
        help="Whether to save to raw"
    )
    
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Show only the first N results"
    )
    
    args = parser.parse_args()
    
    if args.source == "espn_rss":
        logger.info("Testing ESPN RSS fetching...")
        fetcher = ESPNRSSFetcher()
        items = fetcher.fetch(max_items=10)
        
        logger.info(f"Fetched {len(items)} articles")
        
        for i, item in enumerate(items[:args.limit]):
            print(f"\n[{i+1}] {item['title']}")
            print(f"    URL: {item['source_url']}")
            print(f"    Published at: {item['published_at']}")
            print(f"    Preview: {item['raw_text'][:200]}...")
        
        if args.save:
            count = fetcher.save_raw(items)
            logger.info(f"Saved {count} records to raw")
    
    elif args.source == "injuries_pages":
        logger.info("Testing injuries page fetching...")
        fetcher = InjuriesPageFetcher()
        injuries = fetcher.fetch_all()
        
        for source, injury_list in injuries.items():
            logger.info(f"{source}: Found {len(injury_list)} injury records")
            
            for i, injury in enumerate(injury_list[:args.limit]):
                print(f"\n[{source}][{i+1}]")
                print(injury.to_chunk_text())
        
        if args.save:
            count = fetcher.save_raw(injuries)
            logger.info(f"Saved {count} records to raw")


if __name__ == "__main__":
    main()

