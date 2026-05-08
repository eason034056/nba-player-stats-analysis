"""
chunking.py - File Chunking Module

This module is responsible for:
1. Splitting long texts into chunks suitable for embedding
2. Preserving semantic integrity (avoiding splits in the middle of sentences)
3. Generating stable IDs for each chunk

Chunking Strategies:
- ESPN news: recursive splitter, 900-1400 characters
- Injury reports: one chunk per player
- Overlap 120-200 characters to ensure context continuity

Naming Conventions:
- TextChunker: Text chunker class
- DocumentChunk: Data structure for split results
- split(): Main chunking method
"""

import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

from src.config import get_config
from src.logging_utils import get_logger

logger = get_logger(__name__)


@dataclass
class DocumentChunk:
    """
    Data structure for document chunk

    This structure is directly stored in ChromaDB

    Field descriptions:
    - id: Stable chunk ID (used for upsert)
    - text: The text content of the chunk
    - metadata: Related metadata
    """
    id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Convert to dictionary format"""
        return asdict(self)


def generate_chunk_id(
    source: str,
    source_url: str,
    published_at: str,
    chunk_index: int,
    chunk_hash_prefix: str,
) -> str:
    """
    Generate a stable chunk ID

    The ID must be stable (the same content produces the same ID),
    so that an upsert can properly update rather than insert duplicates

    Args:
        source: Source identifier
        source_url: Source URL
        published_at: Published time
        chunk_index: Order in the original text
        chunk_hash_prefix: First 8 characters of content hash

    Returns:
        str: Stable chunk ID

    ID format: sha256(source|url|time|index|hash_prefix)[:16]
    """
    # Combine all elements
    combined = f"{source}|{source_url}|{published_at}|{chunk_index}|{chunk_hash_prefix}"
    
    # Calculate SHA256 and take the first 16 characters
    full_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    
    return full_hash[:16]


def compute_text_hash(text: str) -> str:
    """Compute the hash of text"""
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class TextChunker:
    """
    Text chunker

    Uses a recursive character splitting strategy:
    1. Try paragraph separation (\n\n) first
    2. If too long, split by sentence (.!?)
    3. Finally, split by character

    Example usage:
        chunker = TextChunker(chunk_size=1000, chunk_overlap=150)
        chunks = chunker.split(long_text, metadata={...})
    """
    
    def __init__(
        self,
        chunk_size: int = None,
        chunk_overlap: int = None,
    ):
        """
        Initialize chunker

        Args:
            chunk_size: Target chunk size (character count)
            chunk_overlap: Overlap size (characters)
        """
        config = get_config()
        self.chunk_size = chunk_size or config.chunk_size
        self.chunk_overlap = chunk_overlap or config.chunk_overlap
        
        # Separator priority order
        # Prefer splits at paragraph boundaries, then sentence, finally word
        self.separators = [
            "\n\n",  # paragraph
            "\n",    # line
            ". ",    # sentence
            "! ",
            "? ",
            "; ",
            ", ",    # clause
            " ",     # word
            "",      # character (last resort)
        ]
    
    def split(
        self,
        text: str,
        metadata: Dict[str, Any] = None,
    ) -> List[DocumentChunk]:
        """
        Split text into chunks

        Args:
            text: The text to split
            metadata: Metadata copied to each chunk

        Returns:
            List[DocumentChunk]: The resulting list of chunks

        Process:
        1. Recursively split by separators
        2. Merge small pieces until the target size is reached
        3. Generate chunk ID
        4. Add metadata
        """
        if not text or not text.strip():
            return []
        
        metadata = metadata or {}
        
        # Recursive split
        chunks_text = self._recursive_split(text, self.separators)
        
        # Merge smaller chunks
        merged = self._merge_chunks(chunks_text)
        
        # Build DocumentChunk objects
        result = []
        total = len(merged)
        
        for i, chunk_text in enumerate(merged):
            # Calculate hash
            chunk_hash = compute_text_hash(chunk_text)
            
            # Generate ID
            chunk_id = generate_chunk_id(
                source=metadata.get("source", "unknown"),
                source_url=metadata.get("source_url", ""),
                published_at=metadata.get("published_at", ""),
                chunk_index=i,
                chunk_hash_prefix=chunk_hash[:8],
            )
            
            # Copy and extend metadata
            chunk_metadata = metadata.copy()
            chunk_metadata.update({
                "chunk_index": i,
                "chunk_total": total,
                "hash": chunk_hash,
            })
            
            result.append(DocumentChunk(
                id=chunk_id,
                text=chunk_text,
                metadata=chunk_metadata,
            ))
        
        logger.debug(f"Splitting completed: {len(text)} characters -> {len(result)} chunks")
        return result
    
    def _recursive_split(
        self,
        text: str,
        separators: List[str],
    ) -> List[str]:
        """
        Recursively split text

        This is the core algorithm:
        1. Use the current separator to split
        2. If a piece is too long, use the next separator to split it further

        Args:
            text: Text to split
            separators: Remaining available separators

        Returns:
            List[str]: List of split strings
        """
        if not text:
            return []
        
        if not separators:
            # No separators left, force split by char count
            return self._hard_split(text)
        
        separator = separators[0]
        remaining_separators = separators[1:]
        
        if separator:
            splits = text.split(separator)
        else:
            # Empty string separator = each character
            splits = list(text)
        
        result = []
        
        for split in splits:
            if not split:
                continue
            
            if len(split) <= self.chunk_size:
                # Small enough, append directly
                result.append(split)
            else:
                # Too long, recursively split with next separator
                result.extend(self._recursive_split(split, remaining_separators))
        
        return result
    
    def _hard_split(self, text: str) -> List[str]:
        """
        Force split by character count (last resort)

        Used when no separators can split the text to the target size

        Args:
            text: Text to split

        Returns:
            List[str]: List after hard split
        """
        result = []
        for i in range(0, len(text), self.chunk_size):
            result.append(text[i:i + self.chunk_size])
        return result
    
    def _merge_chunks(self, chunks: List[str]) -> List[str]:
        """
        Merge small pieces and add overlap

        Merge consecutive small chunks until target size is approached
        Also add overlap between chunks to preserve context

        Args:
            chunks: List of split strings

        Returns:
            List[str]: List after merging
        """
        if not chunks:
            return []
        
        merged = []
        current = chunks[0]
        
        for i in range(1, len(chunks)):
            chunk = chunks[i]
            
            # Try to merge
            if len(current) + len(chunk) + 1 <= self.chunk_size:
                current = current + " " + chunk
            else:
                # Current chunk is full, save and start new chunk
                merged.append(current.strip())
                
                # Add overlap: take a portion from the end of current chunk
                overlap_text = self._get_overlap(current)
                current = overlap_text + " " + chunk if overlap_text else chunk
        
        # Save the last chunk
        if current.strip():
            merged.append(current.strip())
        
        return merged
    
    def _get_overlap(self, text: str) -> str:
        """
        Get overlap part

        Take overlap-sized content from the end of the text,
        Prefer splitting at sentence or word boundary

        Args:
            text: Text to take overlap from

        Returns:
            str: Overlap part
        """
        if len(text) <= self.chunk_overlap:
            return text
        
        overlap = text[-self.chunk_overlap:]
        
        # Try to start at a sentence boundary
        for sep in [". ", "! ", "? ", "\n"]:
            idx = overlap.find(sep)
            if idx != -1:
                return overlap[idx + len(sep):]
        
        # At least start at a space
        idx = overlap.find(" ")
        if idx != -1:
            return overlap[idx + 1:]
        
        return overlap


class InjuryChunker:
    """
    Chunker specialized for injury data

    The optimal chunking strategy for injury data is one chunk per player,
    so queries for a player return all relevant information
    """
    
    def chunk_injury(
        self,
        player_name: str,
        team: str,
        status: str,
        injury: str,
        notes: str = None,
        game_date: str = None,
        opponent: str = None,
        metadata: Dict[str, Any] = None,
    ) -> DocumentChunk:
        """
        Create a chunk for a single player's injury

        Args:
            player_name: Player's name
            team: Team code
            status: Injury status
            injury: Injury description
            notes: Additional notes
            game_date: Game date
            opponent: Opponent
            metadata: Additional metadata

        Returns:
            DocumentChunk: Created chunk
        """
        # Build formatted text
        lines = [
            f"TEAM: {team}",
            f"PLAYER: {player_name}",
            f"STATUS: {status}",
            f"INJURY: {injury}",
        ]
        
        if game_date:
            lines.insert(1, f"GAME DATE: {game_date}")
        if opponent:
            lines.insert(2, f"OPPONENT: {opponent}")
        if notes:
            lines.append(f"NOTES: {notes}")
        
        text = "\n".join(lines)
        
        # Compute hash
        chunk_hash = compute_text_hash(text)
        
        # Build metadata
        chunk_metadata = metadata.copy() if metadata else {}
        chunk_metadata.update({
            "team": team,
            "player_names": [player_name],
            "topic": "injury",
            "hash": chunk_hash,
        })
        if game_date:
            chunk_metadata["game_date"] = game_date
        
        # Generate ID
        chunk_id = generate_chunk_id(
            source=chunk_metadata.get("source", "injury_report"),
            source_url=chunk_metadata.get("source_url", ""),
            published_at=chunk_metadata.get("published_at", ""),
            chunk_index=0,
            chunk_hash_prefix=chunk_hash[:8],
        )
        
        return DocumentChunk(
            id=chunk_id,
            text=text,
            metadata=chunk_metadata,
        )


def chunk_document(
    text: str,
    metadata: Dict[str, Any] = None,
    chunk_size: int = None,
    chunk_overlap: int = None,
) -> List[DocumentChunk]:
    """
    Convenience function: chunk a document

    Args:
        text: Text to chunk
        metadata: Metadata
        chunk_size: Chunk size
        chunk_overlap: Overlap size

    Returns:
        List[DocumentChunk]: Chunking results

    Example usage:
        chunks = chunk_document(
            article_text,
            metadata={"source": "espn_rss", "team": "LAL"},
            chunk_size=1000
        )
    """
    chunker = TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return chunker.split(text, metadata)

