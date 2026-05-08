"""
hyde.py - HyDE (Hypothetical Document Embedding) Implementation

HyDE is an advanced RAG technique with the core idea:
1. First, have the LLM generate a "hypothetical document" based on the question.
2. Use this hypothetical document (rather than the original query) for vector retrieval.
3. After retrieving real documents, use the LLM to generate the final answer.

Why is HyDE effective?
- The semantic space of queries and documents are different.
- For example: the question is "Is LeBron playing tonight?"
               the document is "LeBron James is listed as questionable with left ankle soreness."
- HyDE lets the LLM first "guess" what the answer might look like,
  making this guess semantically closer to real documents.

Naming notes:
- HyDERetriever: HyDE retriever class
- generate_hypothetical_document(): Generates the hypothetical document
- query_with_hyde(): Complete HyDE RAG workflow

Reference:
Gao et al., "Precise Zero-Shot Dense Retrieval without Relevance Labels" (2022)
https://arxiv.org/abs/2212.10496
"""

from typing import List, Optional
from dataclasses import dataclass

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from src.config import get_config
from src.logging_utils import get_logger
from src.embeddings import embed_query, embed_passages
from src.vectordb.query import QueryEngine, QueryResult
from src.rag.langchain_rag import RAGOutput, SYSTEM_PROMPT_WITH_RAG

logger = get_logger(__name__)


# HyDE-specific hypothetical document generation prompt
HYDE_GENERATION_PROMPT = """You are an NBA injury report writer.

Based on the following question, please write a "hypothetical injury report" simulating what kind of document the answer to this question would appear in.

## Rules
1. Write a paragraph in the style of an ESPN or official NBA injury report.
2. Include specific details (player name, status, injury description, etc.)
3. The format should be like a real injury report.
4. Do not mention "hypothetical" or "maybe"—just write the report contents directly.

## Example

Question: Will LeBron James play tonight?
Hypothetical report:
TEAM: LAL
PLAYER: LeBron James
STATUS: Questionable
INJURY: Left ankle soreness
The Lakers star has been dealing with ankle soreness but participated in morning shootaround. Coach Ham indicated he will be a game-time decision. James has missed the last two games but is trending towards playing tonight against the Celtics.

Now, please generate a hypothetical report based on the question below:

Question: {question}

Hypothetical report:"""


class HyDERetriever:
    """
    HyDE Retriever

    This class implements the HyDE algorithm:
    1. Generate a hypothetical document using the LLM.
    2. Use the embedding of the hypothetical document for retrieval.
    3. Optionally: Average the embeddings of the original query and the hypothetical document.

    Usage example:
        hyde = HyDERetriever()
        
        # Retrieve only
        results = hyde.retrieve("Is LeBron playing tonight?")
        
        # Full RAG workflow (including answer generation)
        output = hyde.query("Is LeBron playing tonight?")
    
    Attributes:
    - llm: LLM for generating hypothetical documents
    - query_engine: Engine for retrieval
    - blend_factor: Blend factor (0-1), for averaging query and hypothetical embeddings
    """
    
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,  # Higher temperature for more diverse generation
        blend_factor: float = 0.5,
        api_key: str = None,
    ):
        """
        Initialize HyDE Retriever
        
        Args:
            model: LLM for generating hypothetical documents
            temperature: Generation temperature (suggested 0.5-0.8)
            blend_factor: Embedding blend factor
                         - 0: Use only hypothetical document
                         - 1: Use only the original query
                         - 0.5: Average both
            api_key: OpenAI API key
        """
        config = get_config()
        
        self.llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=api_key or config.openai_api_key,
        )
        
        # LLM for final answer generation (lower temperature)
        self.answer_llm = ChatOpenAI(
            model=model,
            temperature=0.3,
            api_key=api_key or config.openai_api_key,
        )
        
        self.query_engine = QueryEngine()
        self.blend_factor = blend_factor
        
        # Prompt template
        self.hyde_prompt = ChatPromptTemplate.from_template(HYDE_GENERATION_PROMPT)
        
        logger.info(f"HyDERetriever initialized: blend_factor={blend_factor}")
    
    def generate_hypothetical_document(self, question: str) -> str:
        """
        Generate a hypothetical document

        This is the core HyDE step: use LLM to generate a
        hypothetical document answering "if an answer exists, what would it look like?"

        Args:
            question: Original question
        
        Returns:
            str: The generated hypothetical document

        Why is this effective?
        - The LLM knows about NBA and injury report style
        - Semantics will be close to real documents
        - Even if the details are not factually correct, the "style" and "vocabulary" will match
        """
        chain = self.hyde_prompt | self.llm | StrOutputParser()
        
        try:
            hypothetical_doc = chain.invoke({"question": question})
            logger.debug(f"Hypothetical doc generated: {hypothetical_doc[:100]}...")
            return hypothetical_doc
        except Exception as e:
            logger.error(f"Failed to generate hypothetical doc: {e}")
            # If failed, return the original question
            return question
    
    def retrieve(
        self,
        question: str,
        team: str = None,
        player: str = None,
        top_k: int = 10,
    ) -> List[QueryResult]:
        """
        Retrieve using HyDE

        Workflow:
        1. Generate hypothetical document
        2. Compute embedding for hypothetical document
        3. Mix with original query embedding
        4. Query ChromaDB with blended embedding

        Args:
            question: Original question
            team: Team filter
            player: Player filter
            top_k: Number of results to retrieve

        Returns:
            List[QueryResult]: Retrieval results
        """
        # 1. Generate hypothetical document
        hypothetical_doc = self.generate_hypothetical_document(question)
        
        # 2. Compute embeddings
        # Hypothetical document uses passage embedding (as it simulates a doc)
        hyde_embedding = embed_passages([hypothetical_doc])[0]
        
        # Original query uses query embedding
        query_embedding = embed_query(question)
        
        # 3. Blend embeddings
        # blended = (1 - blend_factor) * hyde + blend_factor * query
        blended_embedding = (
            (1 - self.blend_factor) * hyde_embedding +
            self.blend_factor * query_embedding
        )
        
        # Normalize
        import numpy as np
        norm = np.linalg.norm(blended_embedding)
        if norm > 1e-12:
            blended_embedding = blended_embedding / norm
        
        # 4. Use blended embedding for retrieval
        # Directly use ChromaDB's low-level query
        from src.vectordb.collections import get_collection_manager, COLLECTION_CONFIGS
        
        collection_manager = get_collection_manager()
        all_results = []
        
        for coll_name in COLLECTION_CONFIGS.keys():
            try:
                collection = collection_manager.get_collection(coll_name)
                
                results = collection.query(
                    query_embeddings=[blended_embedding.tolist()],
                    n_results=top_k,
                    include=["documents", "metadatas", "distances"],
                )
                
                if results["ids"] and results["ids"][0]:
                    for i, id_ in enumerate(results["ids"][0]):
                        distance = results["distances"][0][i]
                        score = 1 / (1 + distance)
                        
                        all_results.append(QueryResult(
                            id=id_,
                            text=results["documents"][0][i],
                            metadata=results["metadatas"][0][i],
                            distance=distance,
                            score=score,
                            collection=coll_name,
                        ))
            except Exception as e:
                logger.warning(f"HyDE retrieval failed for {coll_name}: {e}")
        
        # Sort by score and select top_k
        all_results.sort(key=lambda r: r.score, reverse=True)
        
        # Player filter
        if player:
            player_lower = player.lower()
            all_results = [
                r for r in all_results
                if player_lower in r.text.lower() or
                any(player_lower in p.lower() 
                    for p in r.metadata.get("player_names", []))
            ]
        
        return all_results[:top_k]
    
    def query(
        self,
        question: str,
        team: str = None,
        player: str = None,
        top_k: int = 10,
    ) -> RAGOutput:
        """
        Full HyDE RAG query

        Workflow:
        1. Retrieve relevant docs using HyDE
        2. Format context
        3. Generate answer using LLM

        Args:
            question: Question
            team: Team filter
            player: Player filter
            top_k: Number of results to retrieve

        Returns:
            RAGOutput: The answer and sources
        """
        # 1. HyDE retrieval
        results = self.retrieve(
            question=question,
            team=team,
            player=player,
            top_k=top_k,
        )
        
        if not results:
            return RAGOutput(
                answer="Sorry, no relevant information was found to answer this question.",
                sources=[],
                method="hyde",
            )
        
        # 2. Format context
        context = self._format_context(results)
        
        # 3. Generate answer
        answer_prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT_WITH_RAG),
            ("human", """## Question
{question}

## Context
{context}

Please answer the question based on the context above."""),
        ])
        
        chain = answer_prompt | self.answer_llm | StrOutputParser()
        
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
                }
                for r in results
            ]
            
            return RAGOutput(
                answer=answer,
                sources=sources,
                method="hyde",
                retrieval_scores=[r.score for r in results],
            )
            
        except Exception as e:
            logger.error(f"HyDE answer generation failed: {e}")
            return RAGOutput(
                answer=f"Error: {str(e)}",
                method="hyde",
            )
    
    def _format_context(self, results: List[QueryResult], max_chars: int = 6000) -> str:
        """Format retrieval results as context"""
        lines = []
        total_chars = 0
        
        for i, r in enumerate(results, 1):
            source = r.collection
            date = r.metadata.get("published_at", "unknown")[:10]
            title = r.metadata.get("title", "")
            
            header = f"[{i}] ({source}, {date})"
            if title:
                header += f" - {title}"
            
            entry = f"{header}\n{r.text}\n"
            
            if total_chars + len(entry) > max_chars:
                break
            
            lines.append(entry)
            total_chars += len(entry)
        
        return "\n".join(lines)


def query_with_hyde(question: str, **kwargs) -> RAGOutput:
    """
    Convenience function: Use HyDE for RAG query

    Example:
        from src.rag.hyde import query_with_hyde
        
        result = query_with_hyde("Is LeBron playing tonight?", team="LAL")
        print(result.answer)
    """
    hyde = HyDERetriever()
    return hyde.query(question, **kwargs)
