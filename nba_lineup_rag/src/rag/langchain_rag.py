"""
langchain_rag.py - LangChain RAG Integration Module

This module integrates LangChain with your existing ChromaDB, providing:
1. Basic RAG (Simple RAG)
2. Raw LLM queries (no RAG, as a baseline)
3. Unified query interface

Naming conventions:
- LangChainRAG: Main RAG class
- SimpleRetriever: Simple retriever (wraps ChromaDB)
- query_llm_only(): Use only LLM to answer (no RAG)
- query_simple_rag(): Simple RAG query

Usage Example:
    from src.rag.langchain_rag import LangChainRAG

    rag = LangChainRAG()

    # LLM only (baseline)
    response = rag.query_llm_only("Is LeBron playing tonight?")

    # Simple RAG
    response = rag.query_simple_rag("Is LeBron playing tonight?")
"""

import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_core.documents import Document

from src.config import get_config
from src.logging_utils import get_logger
from src.vectordb.query import QueryEngine, QueryResult
from src.rag.e5_langchain import get_e5_embeddings

logger = get_logger(__name__)


@dataclass
class RAGOutput:
    """
    RAG output structure

    Field descriptions:
    - answer: The generated answer
    - sources: Source documents used
    - method: Method used (llm_only / simple_rag / hyde / rerank)
    - tokens_used: Number of tokens used
    - retrieval_scores: Retrieval scores (if any)
    """
    answer: str
    sources: List[Dict[str, Any]] = field(default_factory=list)
    method: str = ""
    tokens_used: int = 0
    retrieval_scores: List[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "answer": self.answer,
            "sources": self.sources,
            "method": self.method,
            "tokens_used": self.tokens_used,
            "retrieval_scores": self.retrieval_scores,
        }


# System prompts
SYSTEM_PROMPT_NO_RAG = """You are an NBA basketball expert. Please answer questions based on your knowledge.
If you are unsure or information may be outdated, clearly state so.

Note: Your training data has a cutoff date; you may not be able to answer about the latest injuries or game info.
"""

SYSTEM_PROMPT_WITH_RAG = """You are a professional NBA player status analysis assistant.

## Rules
1. Only answer based on the provided "Context". Do not fabricate information.
2. If the context is insufficient, clearly state "Cannot be determined based on current information".
3. When citing information, state the source.
4. For uncertain information, use appropriate wording (such as "may", "expected").

## Injury Status Explanation
- Out: Will not play
- Doubtful: Very unlikely to play (about 25% chance)
- Questionable: Uncertain (about 50% chance to play)
- Probable: Very likely to play (about 75% chance)
- Available: Can play
- GTD (Game-Time Decision): Decision made before the game
"""


class LangChainRAG:
    """
    LangChain RAG Integration Class

    Integrates your existing ChromaDB and E5 embedder,
    and provides a unified interface for several RAG modes.

    Usage Example:
        rag = LangChainRAG(model="gpt-4o-mini")

        # Baseline: LLM only
        baseline = rag.query_llm_only("Is LeBron playing?")

        # Simple RAG
        simple = rag.query_simple_rag("Is LeBron playing?")

    Attributes:
    - llm: LangChain ChatOpenAI instance
    - query_engine: Your existing QueryEngine (for retrieval)
    - embeddings: E5 LangChain Embeddings
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        temperature: float = 0.3,
        api_key: str = None,
    ):
        """
        Initialize LangChain RAG

        Args:
            model: OpenAI model name
                   - gpt-4o-mini: Cheaper, faster, suitable for most scenarios
                   - gpt-4o: More powerful, better for complex reasoning
            temperature: Generation temperature (0-1)
                        - 0: More deterministic, consistent outputs
                        - 1: More random, creative outputs
            api_key: OpenAI API key (if not provided, read from environment variable)
        """
        config = get_config()

        # Set API key
        self.api_key = api_key or config.openai_api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            logger.warning("OPENAI_API_KEY is not set")

        # Initialize LLM
        # ChatOpenAI is LangChain's wrapper for the OpenAI Chat API
        self.llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=self.api_key,
        )

        self.model = model
        self.temperature = temperature

        # Use your existing QueryEngine
        self.query_engine = QueryEngine()

        # E5 embeddings for LangChain
        self.embeddings = get_e5_embeddings()

        logger.info(f"LangChainRAG initialized: model={model}")

    def query_llm_only(
        self,
        question: str,
        team: str = None,
        player: str = None,
    ) -> RAGOutput:
        """
        LLM only response (no RAG) - Baseline

        This method does not use retrieval and relies solely on LLM's training knowledge.
        Used to compare with RAG methods to demonstrate RAG's value.

        Args:
            question: The question
            team: Team (for providing context)
            player: Player (for providing context)

        Returns:
            RAGOutput: Contains the answer and metadata

        Expected behavior:
        - For the latest injuries, the LLM will say "my information may be outdated"
        - For general NBA knowledge, the LLM can answer
        """
        # Build prompt
        # ChatPromptTemplate is LangChain's prompt template class
        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT_NO_RAG),
            ("human", self._build_question_with_context(question, team, player)),
        ])

        # Build chain
        # chain = prompt | llm | output_parser
        # "|" is LangChain's pipeline operator that connects multiple components
        chain = prompt | self.llm | StrOutputParser()

        try:
            # Run the chain
            answer = chain.invoke({})

            return RAGOutput(
                answer=answer,
                sources=[],
                method="llm_only",
            )
        except Exception as e:
            logger.error(f"LLM query failed: {e}")
            return RAGOutput(
                answer=f"Error: {str(e)}",
                method="llm_only",
            )

    def query_simple_rag(
        self,
        question: str,
        team: str = None,
        player: str = None,
        top_k: int = 10,
    ) -> RAGOutput:
        """
        Simple RAG query

        Process:
        1. Use QueryEngine to retrieve relevant documents
        2. Combine documents as context
        3. Present to LLM for answer generation

        Args:
            question: The question
            team: Team filter
            player: Player filter
            top_k: Number of retrievals

        Returns:
            RAGOutput: Contains answer, sources, and metadata
        """
        # 1. Retrieve relevant documents
        results = self.query_engine.query(
            question=question,
            team=team,
            player=player,
            top_k=top_k,
        )

        if not results:
            return RAGOutput(
                answer="Sorry, no relevant information was found to answer this question.",
                sources=[],
                method="simple_rag",
            )

        # 2. Format context
        context = self._format_context(results)

        # 3. Build prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT_WITH_RAG),
            ("human", """## Question
{question}

## Context
The following is information retrieved from the database:

{context}

Please answer the question based on the above context. If context is insufficient, please state so."""),
        ])

        # 4. Build and execute the chain
        chain = prompt | self.llm | StrOutputParser()

        try:
            answer = chain.invoke({
                "question": self._build_question_with_context(question, team, player),
                "context": context,
            })

            # Organize source information
            sources = [
                {
                    "text": r.text[:200] + "..." if len(r.text) > 200 else r.text,
                    "collection": r.collection,
                    "score": r.score,
                    "metadata": r.metadata,
                }
                for r in results
            ]

            return RAGOutput(
                answer=answer,
                sources=sources,
                method="simple_rag",
                retrieval_scores=[r.score for r in results],
            )

        except Exception as e:
            logger.error(f"Simple RAG query failed: {e}")
            return RAGOutput(
                answer=f"Error: {str(e)}",
                method="simple_rag",
            )

    def _build_question_with_context(
        self,
        question: str,
        team: str = None,
        player: str = None,
    ) -> str:
        """
        Build a question that includes context

        Add team/player information to the question so the LLM has more context
        """
        parts = [question]

        if team:
            parts.append(f"(Team: {team})")
        if player:
            parts.append(f"(Player: {player})")

        return " ".join(parts)

    def _format_context(
        self,
        results: List[QueryResult],
        max_chars: int = 6000,
    ) -> str:
        """
        Format retrieval results into a context string

        Args:
            results: Retrieval results
            max_chars: Max character count (to avoid exceeding the context window)

        Returns:
            str: Formatted context
        """
        lines = []
        total_chars = 0

        for i, r in enumerate(results, 1):
            # Format a single result
            source = r.collection
            date = r.metadata.get("published_at", "unknown")[:10]
            title = r.metadata.get("title", "")

            header = f"[{i}] ({source}, {date})"
            if title:
                header += f" - {title}"

            entry = f"{header}\n{r.text}\n"

            # Check length
            if total_chars + len(entry) > max_chars:
                remaining = max_chars - total_chars - 50
                if remaining > 100:
                    truncated = r.text[:remaining] + "...(truncated)"
                    entry = f"{header}\n{truncated}\n"
                    lines.append(entry)
                lines.append(f"\n({len(results) - i} results omitted due to length limit)")
                break

            lines.append(entry)
            total_chars += len(entry)

        return "\n".join(lines)

    def get_retriever(self, top_k: int = 10):
        """
        Get a LangChain-compatible retriever

        This method returns a retriever function that can be used inside a LangChain chain.

        Args:
            top_k: Number of retrievals

        Returns:
            Callable: retriever function
        """
        def retrieve(query: str) -> List[Document]:
            results = self.query_engine.query(
                question=query,
                top_k=top_k,
            )

            # Convert to LangChain Document
            documents = [
                Document(
                    page_content=r.text,
                    metadata={
                        **r.metadata,
                        "collection": r.collection,
                        "score": r.score,
                    }
                )
                for r in results
            ]

            return documents

        return retrieve


def query_llm_only(question: str, **kwargs) -> RAGOutput:
    """
    Convenience function: LLM only query

    Usage Example:
        from src.rag.langchain_rag import query_llm_only
        result = query_llm_only("Is LeBron playing tonight?")
        print(result.answer)
    """
    rag = LangChainRAG()
    return rag.query_llm_only(question, **kwargs)


def query_simple_rag(question: str, **kwargs) -> RAGOutput:
    """
    Convenience function: Simple RAG query

    Usage Example:
        from src.rag.langchain_rag import query_simple_rag
        result = query_simple_rag("Is LeBron playing tonight?", team="LAL")
        print(result.answer)
    """
    rag = LangChainRAG()
    return rag.query_simple_rag(question, **kwargs)
