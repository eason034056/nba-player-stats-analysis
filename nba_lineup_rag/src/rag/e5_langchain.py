"""
e5_langchain.py - E5 Embeddings LangChain Wrapper

This module wraps the E5 embedder as a LangChain-compatible Embeddings class,
allowing you to use the E5 model within the LangChain ecosystem.

Why is this wrapper needed?
- LangChain components such as Chroma require an object that conforms to the Embeddings interface
- The E5 model requires special prefix processing ("query:" / "passage:")
- This wrapper automatically handles these details

Naming Notes:
- E5LangChainEmbeddings: The main LangChain Embeddings class
- embed_documents(): Embed multiple documents (LangChain standard method)
- embed_query(): Embed a single query (LangChain standard method)

Usage Example:
    from src.rag.e5_langchain import E5LangChainEmbeddings

    embeddings = E5LangChainEmbeddings()

    # For LangChain Chroma usage
    from langchain_chroma import Chroma
    vectorstore = Chroma(
        persist_directory="data/chroma",
        embedding_function=embeddings
    )
"""

from typing import List
import numpy as np

from langchain_core.embeddings import Embeddings

from src.embeddings.e5_embedder import E5Embedder, get_embedder


class E5LangChainEmbeddings(Embeddings):
    """
    LangChain wrapper for E5 Embeddings

    This class inherits from LangChain's Embeddings base class
    and implements the two required methods: embed_documents() and embed_query().

    Attributes:
    - embedder: The underlying E5Embedder instance
    - model_name: The name of the model being used

    Usage Example:
        embeddings = E5LangChainEmbeddings()

        # Embed documents
        doc_vectors = embeddings.embed_documents(["doc1", "doc2"])

        # Embed query
        query_vector = embeddings.embed_query("What is the injury status?")
    """

    def __init__(
        self,
        model_name: str = None,
        device: str = None,
        use_singleton: bool = True,
    ):
        """
        Initialize E5 LangChain Embeddings

        Args:
            model_name: Model name, default 'intfloat/e5-large-v2'
            device: Computation device, 'cpu' or 'cuda'
            use_singleton: Whether to use a global singleton (to save memory)

        About use_singleton:
        - True: Use get_embedder() to get a shared embedder instance
        - False: Create a new embedder instance (for testing or special cases)
        """
        if use_singleton and model_name is None and device is None:
            # Use global singleton to avoid reloading the model
            self.embedder = get_embedder()
        else:
            # Create new instance
            self.embedder = E5Embedder(
                model_name=model_name,
                device=device,
            )

        self.model_name = self.embedder.model_name

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embed multiple documents

        This is a required method for the LangChain Embeddings interface.
        It automatically adds a "passage: " prefix and performs L2 normalization.

        Args:
            texts: List of document strings

        Returns:
            List[List[float]]: List of embedding vectors, each as a list of floats

        Why return List[List[float]]?
        - The LangChain interface requires this return format
        - Numpy arrays must be converted to Python lists
        """
        if not texts:
            return []

        # Use the embed_passages method from E5Embedder,
        # which adds the "passage: " prefix and normalizes
        embeddings = self.embedder.embed_passages(texts)

        # Convert to List[List[float]] format
        return embeddings.tolist()

    def embed_query(self, text: str) -> List[float]:
        """
        Embed a single query

        This is a required method for the LangChain Embeddings interface.
        It automatically adds a "query: " prefix and performs L2 normalization.

        Args:
            text: Query string

        Returns:
            List[float]: Embedding vector

        Why are the prefixes different for queries and documents?
        - The E5 model was trained with different prefixes to distinguish queries and documents
        - This helps the model learn the relationship between "questions" and "answers"
        - For example, "query: Is LeBron playing?" would have a high similarity to
          "passage: LeBron James is questionable"
        """
        # Use the embed_query method from E5Embedder
        embedding = self.embedder.embed_query(text)

        # Convert to List[float] format
        return embedding.tolist()

    @property
    def embedding_dimension(self) -> int:
        """
        Get the dimensionality of the embedding vectors

        Returns:
            int: Embedding dimension (e5-large-v2 is 1024)
        """
        return self.embedder.embedding_dim


def get_e5_embeddings() -> E5LangChainEmbeddings:
    """
    Convenience function: Get an E5 LangChain Embeddings instance

    Uses a global singleton pattern to avoid reloading the model.

    Returns:
        E5LangChainEmbeddings: embeddings instance

    Usage Example:
        from src.rag.e5_langchain import get_e5_embeddings

        embeddings = get_e5_embeddings()
        vectorstore = Chroma(embedding_function=embeddings)
    """
    return E5LangChainEmbeddings(use_singleton=True)
