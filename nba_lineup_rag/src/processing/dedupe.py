"""
dedupe.py - Deduplication Module

This module is responsible for:
1. Detecting duplicate content using a hash
2. Detecting duplicate sources using source_url + published_at
3. Tracking already-processed items to avoid repeated processing

Deduplication strategy:
- Raw level: Use source_url + published_at as key
- Chunk level: Use content hash as key

Naming conventions:
- Deduplicator: deduplication class
- is_duplicate(): check for duplication
- add(): add an item to the known set
"""

import hashlib
import json
from pathlib import Path
from typing import Set, Dict, Optional, List, Any
from dataclasses import dataclass

from src.logging_utils import get_logger

logger = get_logger(__name__)


def compute_hash(text: str) -> str:
    """
    Compute the SHA256 hash of a text string

    This is the core of deduplication: identical content -> identical hash

    Args:
        text: text for which to compute the hash

    Returns:
        str: 64-character hexadecimal hash
    """
    # Normalize: remove extra spaces, lowercase
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_source_key(source_url: str, published_at: str) -> str:
    """
    Compute a unique key for a source

    Used for deduplication at the raw data level: same source + publication time are considered the same

    Args:
        source_url: source URL
        published_at: publication time

    Returns:
        str: combined key string
    """
    return f"{source_url}|{published_at}"


@dataclass
class DuplicateCheckResult:
    """
    Result of deduplication check

    Fields:
    - is_duplicate: whether this is a duplicate
    - duplicate_type: type of duplicate ('hash', 'source_key', or None)
    - existing_id: ID of the existing item (if any)
    """
    is_duplicate: bool
    duplicate_type: Optional[str] = None
    existing_id: Optional[str] = None


class Deduplicator:
    """
    Deduplication class

    Maintains sets of known items for fast duplicate checking

    Example usage:
        dedup = Deduplicator()
        
        # Load existing data
        dedup.load_from_raw_dir(raw_dir)
        
        # Check new items
        for item in new_items:
            result = dedup.check(item)
            if result.is_duplicate:
                print(f"Skip duplicate: {result.duplicate_type}")
            else:
                # Process new item
                dedup.add(item)
    """
    
    def __init__(self):
        """Initialize deduplicator"""
        # Set of known content hashes
        # Set provides O(1) lookup
        self._content_hashes: Set[str] = set()
        
        # Set of known source keys (source_url + published_at)
        self._source_keys: Set[str] = set()
        
        # hash -> item_id mapping (optional, for tracking)
        self._hash_to_id: Dict[str, str] = {}
    
    def check(
        self,
        content: str = None,
        content_hash: str = None,
        source_url: str = None,
        published_at: str = None,
    ) -> DuplicateCheckResult:
        """
        Check if an item is a duplicate

        You can check by content, hash, or source info

        Args:
            content: raw content (hash will be computed automatically)
            content_hash: pre-computed hash
            source_url: source URL
            published_at: publication time

        Returns:
            DuplicateCheckResult: result of duplication check

        Example usage:
            # By content
            result = dedup.check(content="Hello World")
            
            # By hash
            result = dedup.check(content_hash="abc123...")
            
            # By source info
            result = dedup.check(source_url="https://...", published_at="2026-01-27")
        """
        # Prefer hash check (more precise)
        if content_hash or content:
            h = content_hash or compute_hash(content)
            if h in self._content_hashes:
                return DuplicateCheckResult(
                    is_duplicate=True,
                    duplicate_type="hash",
                    existing_id=self._hash_to_id.get(h),
                )
        
        # Then check source key
        if source_url and published_at:
            source_key = compute_source_key(source_url, published_at)
            if source_key in self._source_keys:
                return DuplicateCheckResult(
                    is_duplicate=True,
                    duplicate_type="source_key",
                )
        
        return DuplicateCheckResult(is_duplicate=False)
    
    def add(
        self,
        content: str = None,
        content_hash: str = None,
        source_url: str = None,
        published_at: str = None,
        item_id: str = None,
    ):
        """
        Add an item to the known set

        Args:
            content: raw content
            content_hash: pre-computed hash
            source_url: source URL
            published_at: publication time
            item_id: item ID (optional)
        """
        # Add hash
        if content_hash or content:
            h = content_hash or compute_hash(content)
            self._content_hashes.add(h)
            if item_id:
                self._hash_to_id[h] = item_id
        
        # Add source key
        if source_url and published_at:
            source_key = compute_source_key(source_url, published_at)
            self._source_keys.add(source_key)
    
    def load_from_raw_dir(self, raw_dir: Path):
        """
        Load hashes and source keys from a raw data directory

        Call this at startup to ensure you don't reprocess data

        Args:
            raw_dir: path to raw data directory
        """
        raw_dir = Path(raw_dir)
        if not raw_dir.exists():
            logger.info(f"Raw directory does not exist: {raw_dir}")
            return
        
        count = 0
        
        # Walk through all subfolders and JSONL files
        for jsonl_file in raw_dir.rglob("*.jsonl"):
            try:
                with open(jsonl_file, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            item = json.loads(line)
                            
                            # Extract hash
                            if "raw_hash" in item:
                                self._content_hashes.add(item["raw_hash"])
                            
                            # Extract source key
                            if "source_url" in item and "published_at" in item:
                                source_key = compute_source_key(
                                    item["source_url"],
                                    item["published_at"]
                                )
                                self._source_keys.add(source_key)
                            
                            count += 1
                        except json.JSONDecodeError:
                            pass
            except Exception as e:
                logger.warning(f"Failed to load file: {jsonl_file} - {e}")
        
        logger.info(
            f"Loaded deduplication data from {raw_dir}: "
            f"{len(self._content_hashes)} hashes, "
            f"{len(self._source_keys)} source keys"
        )
    
    def load_from_items(self, items: List[Dict[str, Any]]):
        """
        Load from a list of items

        Args:
            items: list of RawItem or similar structures
        """
        for item in items:
            self.add(
                content_hash=item.get("raw_hash"),
                source_url=item.get("source_url"),
                published_at=item.get("published_at"),
            )
    
    @property
    def stats(self) -> dict:
        """
        Get statistics

        Returns:
            dict: counts of known hashes and source keys
        """
        return {
            "content_hashes": len(self._content_hashes),
            "source_keys": len(self._source_keys),
        }
    
    def clear(self):
        """Clear all known items"""
        self._content_hashes.clear()
        self._source_keys.clear()
        self._hash_to_id.clear()


def dedupe_items(items: List[Dict], key_field: str = "raw_hash") -> List[Dict]:
    """
    Convenience function: deduplicate a list of items

    Keep only the first item for each unique key

    Args:
        items: list of items
        key_field: field to use as deduplication key

    Returns:
        List[Dict]: deduplicated list

    Example usage:
        unique_items = dedupe_items(items, key_field="raw_hash")
    """
    seen = set()
    unique = []
    
    for item in items:
        key = item.get(key_field)
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
        elif not key:
            # Keep all items with no key
            unique.append(item)
    
    logger.info(f"Deduplicated: {len(items)} -> {len(unique)} (removed {len(items) - len(unique)} duplicates)")
    return unique

