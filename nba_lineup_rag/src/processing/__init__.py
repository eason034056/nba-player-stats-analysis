"""
processing - Data Processing Module

This package includes all steps of data processing:
- normalize: Text normalization (cleaning, formatting)
- dedupe: Deduplication (avoiding duplicate data)
- chunking: Document chunking (splitting long texts into smaller pieces)
- extract_entities: Entity extraction (teams, players, dates)

Processing pipeline:
Raw Text -> Normalize -> Extract Entities -> Chunk -> Ready for Embedding
"""

from .normalize import normalize_text, clean_html
from .dedupe import Deduplicator
from .chunking import TextChunker, DocumentChunk
from .extract_entities import EntityExtractor

__all__ = [
    "normalize_text",
    "clean_html",
    "Deduplicator",
    "TextChunker",
    "DocumentChunk",
    "EntityExtractor",
]

