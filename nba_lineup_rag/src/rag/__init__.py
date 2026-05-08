"""
rag - RAG Inference Module

This package is responsible for passing retrieved evidence to Large Language Models (LLM) for reasoning:
- prompts: prompt templates
- answer: answer generation
- langchain_rag: LangChain integration (Part 2)
- hyde: HyDE advanced retrieval (Part 2)
- reranker: reranking advanced retrieval (Part 2)
- e5_langchain: E5 LangChain wrapper (Part 2)

RAG (Retrieval-Augmented Generation) Workflow:
1. User asks a question
2. Retrieve relevant context pieces from a vector store
3. Pass these pieces as context to the LLM
4. The LLM generates answers based on the context

New features in Part 2:
- LangChain integration
- HyDE (Hypothetical Document Embeddings)
- Reranking (cross-encoder)
"""

from .prompts import build_prompt, SYSTEM_PROMPT
from .answer import RAGEngine, generate_answer

# Part 2: LangChain Integration
from .langchain_rag import (
    LangChainRAG,
    RAGOutput,
    query_llm_only,
    query_simple_rag,
)

# Part 2: Advanced RAG Techniques
from .hyde import HyDERetriever, query_with_hyde
from .reranker import (
    CrossEncoderReranker,
    RerankedRAG,
    query_with_rerank,
)

# Part 2: E5 LangChain Wrapper
from .e5_langchain import E5LangChainEmbeddings, get_e5_embeddings

__all__ = [
    # Original
    "build_prompt",
    "SYSTEM_PROMPT",
    "RAGEngine",
    "generate_answer",
    # Part 2: LangChain
    "LangChainRAG",
    "RAGOutput",
    "query_llm_only",
    "query_simple_rag",
    # Part 2: HyDE
    "HyDERetriever",
    "query_with_hyde",
    # Part 2: Reranker
    "CrossEncoderReranker",
    "RerankedRAG",
    "query_with_rerank",
    # Part 2: E5 Wrapper
    "E5LangChainEmbeddings",
    "get_e5_embeddings",
]

