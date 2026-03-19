"""
embeddings - Vector Embedding Module

This package is responsible for converting text into vectors (embeddings):
- e5_embedder: Uses the intfloat/e5-large-v2 model

E5 model features:
1. Requires prefix: passage/query
2. Vectors need to be L2 normalized
3. Suitable for semantic similarity search
"""

from .e5_embedder import E5Embedder, embed_passages, embed_query

__all__ = [
    "E5Embedder",
    "embed_passages",
    "embed_query",
]
