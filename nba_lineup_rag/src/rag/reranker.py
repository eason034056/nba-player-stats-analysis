"""
reranker.py - Reranking Implementation

Reranking is a two-stage retrieval strategy:
1. First stage: Use vector retrieval to obtain many candidate documents (e.g., top-50)
2. Second stage: Use a more precise model to re-rank the candidate documents and select the top-k

Why do we need Reranking?
- Vector retrieval (bi-encoder) is fast but not sufficiently accurate
- Cross-encoder is more accurate but slow (not practical for full retrieval)
- Two-stage combination: use bi-encoder to narrow the candidates, then use cross-encoder to re-rank

This module provides two reranking methods:
1. Cross-Encoder Reranking: Uses a pre-trained cross-encoder model
2. LLM Reranking: Uses LLM for scoring (slower but potentially more accurate)

Naming explanation:
- CrossEncoderReranker: Reranker using a cross-encoder model
- LLMReranker: Reranker using LLM scoring
- RerankedRAG: RAG class with integrated reranking

References:
- Cross-Encoder: https://www.sbert.net/docs/cross_encoder/usage/usage.html
- MS MARCO MiniLM: A model trained specifically for passage re-ranking
"""

from typing import List, Tuple, Optional
from dataclasses import dataclass
import numpy as np

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from src.config import get_config
from src.logging_utils import get_logger
from src.vectordb.query import QueryEngine, QueryResult
from src.rag.langchain_rag import RAGOutput, SYSTEM_PROMPT_WITH_RAG

logger = get_logger(__name__)


class CrossEncoderReranker:
    """
    Cross-Encoder Reranker
    
    Uses the CrossEncoder model from sentence-transformers to re-rank documents.
    
    Cross-Encoder vs Bi-Encoder:
    - Bi-Encoder: Encodes query and document separately. Uses dot product for similarity.
      - Pros: document embeddings can be precomputed, retrieval is fast
      - Cons: no interaction between query and document, lower accuracy
    
    - Cross-Encoder: Inputs query and document together, computes a relevance score
      - Pros: deep interaction between query and document, higher accuracy
      - Cons: cannot precompute, must calculate for each (query, doc) pair
    
    Example usage:
        reranker = CrossEncoderReranker()
        
        # Assuming `results` contains initial hits from a bi-encoder
        reranked = reranker.rerank("Is LeBron playing?", results, top_k=5)
    
    Attributes:
    - model: CrossEncoder model instance
    - model_name: Name of the model used
    """
    
    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        device: str = None,
    ):
        """
        Initialize Cross-Encoder Reranker
        
        Args:
            model_name: Name of the Cross-Encoder model
                        Recommended options:
                        - cross-encoder/ms-marco-MiniLM-L-6-v2: Small and fast (recommended)
                        - cross-encoder/ms-marco-TinyBERT-L-2-v2: Smaller, even faster
                        - cross-encoder/ms-marco-MiniLM-L-12-v2: Larger, more accurate
            device: computation device ('cpu' or 'cuda')
        
        Model size reference:
        - L-2: ~66MB, fastest
        - L-6: ~90MB, balanced
        - L-12: ~134MB, most accurate
        """
        from sentence_transformers import CrossEncoder
        
        config = get_config()
        self.device = device or config.embedding_device
        self.model_name = model_name
        
        logger.info(f"Loading CrossEncoder: {model_name}")
        self.model = CrossEncoder(model_name, device=self.device)
        logger.info("CrossEncoder loaded")
    
    def rerank(
        self,
        query: str,
        results: List[QueryResult],
        top_k: int = 10,
    ) -> List[QueryResult]:
        """
        Re-rank retrieved results
        
        Args:
            query: the search query
            results: initial retrieval results
            top_k: how many top results to keep after re-ranking
        
        Returns:
            List[QueryResult]: results after re-ranking
        
        Steps:
        1. Pair each result's text with the query
        2. Use CrossEncoder to compute a relevance score for each pair
        3. Sort results by score descending
        4. Take top_k
        """
        if not results:
            return []
        
        # Create (query, document) pairs needed by CrossEncoder
        pairs = [(query, r.text) for r in results]
        
        # Compute relevance scores
        # predict() returns a score per pair, usually in [-10, 10]
        scores = self.model.predict(pairs)
        
        # Attach scores to results
        scored_results = list(zip(results, scores))
        
        # Sort descending by score
        scored_results.sort(key=lambda x: x[1], reverse=True)
        
        # Update each result with new score
        reranked = []
        for result, score in scored_results[:top_k]:
            reranked.append(QueryResult(
                id=result.id,
                text=result.text,
                metadata=result.metadata,
                distance=result.distance,
                score=float(score),  # use reranking score
                collection=result.collection,
            ))
        
        logger.debug(f"Reranking complete: {len(results)} -> {len(reranked)}")
        return reranked


class LLMReranker:
    """
    LLM Reranker
    
    Uses an LLM to score the relevance of documents.
    
    Pros:
    - Can understand complex semantic relationships
    - No need for an extra cross-encoder model
    
    Cons:
    - Much slower than cross-encoder
    - Consumes API tokens
    
    Example usage:
        reranker = LLMReranker()
        reranked = reranker.rerank("Is LeBron playing?", results, top_k=5)
    """
    
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str = None,
    ):
        """
        Initialize LLM Reranker
        
        Args:
            model: OpenAI model name
            api_key: API key
        """
        config = get_config()
        
        self.llm = ChatOpenAI(
            model=model,
            temperature=0,  # Consistent ratings are required
            api_key=api_key or config.openai_api_key,
        )
        
        # Scoring prompt
        self.score_prompt = ChatPromptTemplate.from_template(
            """Please evaluate the relevance between the following document and question.

Question: {query}

Document:
{document}

Please provide a relevance score from 0 to 10:
- 0: Not relevant at all
- 1-3: Slightly related but does not answer the question
- 4-6: Partially relevant, might be helpful
- 7-9: Highly relevant, can answer the question
- 10: Perfect match, directly answers the question

Only reply a single number (0-10), nothing else.

Score:"""
        )
    
    def rerank(
        self,
        query: str,
        results: List[QueryResult],
        top_k: int = 10,
    ) -> List[QueryResult]:
        """
        Re-rank results using LLM
        
        Note: This method calls the LLM for each result, which is slow and consumes tokens.
        It is recommended to narrow down candidates to 20-30 with a bi-encoder first.
        """
        if not results:
            return []
        
        scored_results = []
        
        for result in results:
            try:
                # Call LLM to score
                chain = self.score_prompt | self.llm | StrOutputParser()
                score_text = chain.invoke({
                    "query": query,
                    "document": result.text[:1000],  # Limit length
                })
                
                # Parse score
                score = float(score_text.strip())
                score = max(0, min(10, score))  # Clamp between 0 and 10
                
                scored_results.append((result, score))
                
            except Exception as e:
                logger.warning(f"LLM scoring failed: {e}")
                # Use original score if failed
                scored_results.append((result, result.score * 10))
        
        # Sort descending
        scored_results.sort(key=lambda x: x[1], reverse=True)
        
        # Build new results
        reranked = []
        for result, score in scored_results[:top_k]:
            reranked.append(QueryResult(
                id=result.id,
                text=result.text,
                metadata=result.metadata,
                distance=result.distance,
                score=score,
                collection=result.collection,
            ))
        
        return reranked


class RerankedRAG:
    """
    RAG with integrated reranking
    
    Steps:
    1. Use a bi-encoder to retrieve many candidates (e.g., 50)
    2. Use cross-encoder to re-rank
    3. Take top-k as context
    4. Use LLM to generate the answer
    
    Example usage:
        rag = RerankedRAG()
        result = rag.query("Is LeBron playing tonight?")
        print(result.answer)
    """
    
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        reranker_type: str = "cross_encoder",
        initial_top_k: int = 30,
        final_top_k: int = 10,
        api_key: str = None,
    ):
        """
        Initialize Reranked RAG
        
        Args:
            model: LLM for answer generation
            reranker_type: reranker type
                          - "cross_encoder": uses CrossEncoder (recommended)
                          - "llm": uses LLM scoring
            initial_top_k: number of initial retrieval results
            final_top_k: number of candidates to keep after reranking
            api_key: API key
        """
        config = get_config()
        
        self.llm = ChatOpenAI(
            model=model,
            temperature=0.3,
            api_key=api_key or config.openai_api_key,
        )
        
        self.query_engine = QueryEngine()
        
        # Initialize reranker
        if reranker_type == "cross_encoder":
            self.reranker = CrossEncoderReranker()
        else:
            self.reranker = LLMReranker(api_key=api_key)
        
        self.reranker_type = reranker_type
        self.initial_top_k = initial_top_k
        self.final_top_k = final_top_k
        
        logger.info(
            f"RerankedRAG initialized: reranker={reranker_type}, "
            f"initial_k={initial_top_k}, final_k={final_top_k}"
        )
    
    def query(
        self,
        question: str,
        team: str = None,
        player: str = None,
    ) -> RAGOutput:
        """
        Query using RAG with reranking
        
        Args:
            question: the input question
            team: filter by team
            player: filter by player
        
        Returns:
            RAGOutput: includes answer and sources
        """
        # 1. Initial retrieval (many candidates)
        initial_results = self.query_engine.query(
            question=question,
            team=team,
            player=player,
            top_k=self.initial_top_k,
        )
        
        if not initial_results:
            return RAGOutput(
                answer="Sorry, no relevant information found to answer this question.",
                sources=[],
                method=f"rerank_{self.reranker_type}",
            )
        
        # 2. Reranking
        reranked_results = self.reranker.rerank(
            query=question,
            results=initial_results,
            top_k=self.final_top_k,
        )
        
        # 3. Format context
        context = self._format_context(reranked_results)
        
        # 4. Generate answer
        answer_prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT_WITH_RAG),
            ("human", """## Question
{question}

## Context
The following are highly relevant information after sorting:

{context}

Please answer the question according to the above context."""),
        ])
        
        chain = answer_prompt | self.llm | StrOutputParser()
        
        try:
            answer = chain.invoke({
                "question": question,
                "context": context,
            })
            
            sources = [
                {
                    "text": r.text[:200] + "..." if len(r.text) > 200 else r.text,
                    "collection": r.collection,
                    "score": r.score,
                    "reranked": True,
                }
                for r in reranked_results
            ]
            
            return RAGOutput(
                answer=answer,
                sources=sources,
                method=f"rerank_{self.reranker_type}",
                retrieval_scores=[r.score for r in reranked_results],
            )
            
        except Exception as e:
            logger.error(f"Reranked RAG answer generation failed: {e}")
            return RAGOutput(
                answer=f"Error: {str(e)}",
                method=f"rerank_{self.reranker_type}",
            )
    
    def _format_context(self, results: List[QueryResult], max_chars: int = 6000) -> str:
        """Format retrieval results as context"""
        lines = []
        total_chars = 0
        
        for i, r in enumerate(results, 1):
            source = r.collection
            date = r.metadata.get("published_at", "unknown")[:10]
            score = r.score
            
            header = f"[{i}] ({source}, {date}, relevance: {score:.2f})"
            entry = f"{header}\n{r.text}\n"
            
            if total_chars + len(entry) > max_chars:
                break
            
            lines.append(entry)
            total_chars += len(entry)
        
        return "\n".join(lines)


def query_with_rerank(question: str, **kwargs) -> RAGOutput:
    """
    Convenience function: Use Reranking for RAG QA
    
    Example usage:
        from src.rag.reranker import query_with_rerank
        
        result = query_with_rerank("Is LeBron playing tonight?", team="LAL")
        print(result.answer)
    """
    rag = RerankedRAG()
    return rag.query(question, **kwargs)
