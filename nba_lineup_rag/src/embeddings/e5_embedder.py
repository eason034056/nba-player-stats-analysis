"""
e5_embedder.py - E5 model vector embedding module

This module is responsible for:
1. Loading the intfloat/e5-large-v2 model
2. Converting text to vectors
3. Properly handling E5 prefix requirements

E5 model usage notes:
- E5 (Embeddings from bidirectional Encoder representations) is an embedding model developed by Microsoft
- E5 requires a prefix in front of the text to distinguish between documents and queries:
  - Document (content to be searched): add "passage: " prefix
  - Query (search question): add "query: " prefix
- Vectors must be L2 normalized for correct use with cosine similarity

Naming conventions:
- E5Embedder: E5 embedder class
- embed_passages(): Embed documents (add passage prefix)
- embed_query(): Embed query (add query prefix)
"""

import numpy as np
from typing import List, Union
import torch
from sentence_transformers import SentenceTransformer

from src.config import get_config
from src.logging_utils import get_logger

logger = get_logger(__name__)


def normalize_l2(vectors: np.ndarray) -> np.ndarray:
    """
    L2 normalize vectors

    L2 normalization (aka unit vector normalization) makes every vector's length (norm) equal to 1.
    This is important for cosine similarity because:
    cosine_similarity(a, b) = dot(a, b) / (norm(a) * norm(b))
    When both a and b are unit vectors, cosine_similarity = dot(a, b)

    Args:
        vectors: array of shape (n, d)
                 n = number of vectors, d = vector dimension

    Returns:
        np.ndarray: normalized vectors

    Formula:
        normalized_v = v / ||v||
        where ||v|| = sqrt(sum(v_i^2))
    """
    # Compute L2 norm for each vector
    # axis=1 calculates along rows (each vector)
    # keepdims=True keeps dimensions for broadcasting
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    
    # Avoid division by zero
    norms = np.maximum(norms, 1e-12)
    
    return vectors / norms


class E5Embedder:
    """
    E5 model embedder

    This class encapsulates loading and using the E5 model,
    automatically handling prefixing and L2 normalization

    Example usage:
        embedder = E5Embedder()
        
        # Embed documents (to be stored in a vector database)
        doc_embeddings = embedder.embed_passages([
            "LeBron James is questionable for tonight's game",
            "Anthony Davis will return from injury"
        ])
        
        # Embed a query (for search)
        query_embedding = embedder.embed_query("Will LeBron play tonight?")

    Vector dimension:
        e5-large-v2 outputs 1024-dimensional vectors
    """
    
    def __init__(
        self,
        model_name: str = None,
        device: str = None,
        batch_size: int = 32,
    ):
        """
        Initialize embedder

        Args:
            model_name: model name, default 'intfloat/e5-large-v2'
            device: computation device, 'cpu' or 'cuda'
            batch_size: batch size for encoding

        Notes:
        - Model will be automatically downloaded from Hugging Face (on first use)
        - The model is about 1.3GB and may take some time to download
        - Using GPU can greatly accelerate embedding
        """
        config = get_config()
        
        self.model_name = model_name or config.embedding_model
        self.device = device or config.embedding_device
        self.batch_size = batch_size
        
        logger.info(f"Loading E5 model: {self.model_name} (device: {self.device})")
        
        # Load SentenceTransformer model
        # SentenceTransformer is the main class in the sentence-transformers package
        # It wraps a Hugging Face transformers model
        self.model = SentenceTransformer(
            self.model_name,
            device=self.device,
        )
        
        # Get embedding dimension
        self.embedding_dim = self.model.get_sentence_embedding_dimension()
        logger.info(f"Model loaded, embedding dimension: {self.embedding_dim}")
    
    def embed_passages(self, texts: List[str]) -> np.ndarray:
        """
        Embed passages (documents)
        
        This method embeds content to be searched,
        and automatically adds the "passage: " prefix

        Args:
            texts: list of document strings

        Returns:
            np.ndarray: array shaped (len(texts), embedding_dim)

        Why add a prefix?
            The E5 model was trained with prefixes to distinguish queries from documents,
            so the model has learned:
            - "passage: ..." is content to be searched
            - "query: ..." is the user's question
            Using the correct prefix will improve search quality
        """
        if not texts:
            return np.array([])
        
        # Add passage prefix
        # E5 requires documents to use the "passage: " prefix
        prefixed_texts = [f"passage: {text}" for text in texts]
        
        logger.debug(f"Embedding {len(texts)} passages")
        
        # Use model.encode to compute embeddings
        # convert_to_numpy=True returns numpy array
        # show_progress_bar=True shows a progress bar (helpful for large batches)
        # batch_size controls number of texts processed at once
        embeddings = self.model.encode(
            prefixed_texts,
            convert_to_numpy=True,
            show_progress_bar=len(texts) > 100,
            batch_size=self.batch_size,
        )
        
        # L2 normalization
        embeddings = normalize_l2(embeddings)
        
        return embeddings
    
    def embed_query(self, text: str) -> np.ndarray:
        """
        Embed query

        This method embeds a search query,
        and automatically adds the "query: " prefix

        Args:
            text: query string

        Returns:
            np.ndarray: shape (embedding_dim,) a one-dimensional vector

        Example usage:
            query_vec = embedder.embed_query("Is LeBron playing tonight?")
            # Use query_vec for vector search in a database
        """
        # Add query prefix
        prefixed_text = f"query: {text}"
        
        logger.debug(f"Embedding query: {text[:50]}...")
        
        # Embed, then normalize
        embedding = self.model.encode(
            prefixed_text,
            convert_to_numpy=True,
        )
        
        # L2 normalization of a single vector
        norm = np.linalg.norm(embedding)
        if norm > 1e-12:
            embedding = embedding / norm
        
        return embedding
    
    def embed_batch(
        self,
        texts: List[str],
        is_query: bool = False,
    ) -> np.ndarray:
        """
        Batch embedding

        A unified embedding interface; chooses prefix based on is_query

        Args:
            texts: list of text strings
            is_query: whether texts are queries (True uses query prefix, False uses passage prefix)

        Returns:
            np.ndarray: array of embeddings
        """
        if is_query:
            # Usually queries are single text, but batch is supported
            prefix = "query: "
        else:
            prefix = "passage: "
        
        prefixed_texts = [f"{prefix}{text}" for text in texts]
        
        embeddings = self.model.encode(
            prefixed_texts,
            convert_to_numpy=True,
            show_progress_bar=len(texts) > 100,
            batch_size=self.batch_size,
        )
        
        return normalize_l2(embeddings)


# Global embedder instance (lazy loading)
_embedder: E5Embedder = None


def get_embedder() -> E5Embedder:
    """
    Get global embedder instance

    Uses singleton pattern to avoid loading model multiple times

    Returns:
        E5Embedder: embedder instance
    """
    global _embedder
    if _embedder is None:
        _embedder = E5Embedder()
    return _embedder


def embed_passages(texts: List[str]) -> np.ndarray:
    """
    Convenience function: embed documents

    Args:
        texts: list of document strings

    Returns:
        np.ndarray: array of embeddings

    Example usage:
        from src.embeddings import embed_passages
        vectors = embed_passages(["doc1", "doc2", "doc3"])
    """
    return get_embedder().embed_passages(texts)


def embed_query(text: str) -> np.ndarray:
    """
    Convenience function: embed query

    Args:
        text: query string

    Returns:
        np.ndarray: query embedding

    Example usage:
        from src.embeddings import embed_query
        query_vec = embed_query("Who is injured on the Lakers?")
    """
    return get_embedder().embed_query(text)

