"""
answer.py - Answer Generation Module

This module is responsible for:
1. Sending evidence and questions to the LLM
2. Handling LLM responses
3. Parsing structured output

Naming conventions:
- RAGEngine: RAG engine class
- generate_answer(): convenience function for generating answers
- parse_assessment(): parses player assessment JSON
"""

import json
import re
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from src.config import get_config
from src.logging_utils import get_logger
from src.vectordb.query import QueryEngine, QueryResult
from src.rag.prompts import SYSTEM_PROMPT, build_prompt, build_assessment_prompt

logger = get_logger(__name__)


@dataclass
class RAGResponse:
    """
    RAG Response Structure

    Field descriptions:
    - answer: generated answer text
    - evidence: list of evidence used
    - model: model name used
    - tokens_used: number of tokens used (if any)
    """
    answer: str
    evidence: List[QueryResult]
    model: str = ""
    tokens_used: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "answer": self.answer,
            "evidence_count": len(self.evidence),
            "model": self.model,
            "tokens_used": self.tokens_used,
        }


class RAGEngine:
    """
    RAG Engine

    Integrates retrieval and LLM generation to provide end-to-end QA capability

    Example usage:
        engine = RAGEngine()

        response = engine.ask(
            question="Is LeBron playing tonight?",
            team="LAL"
        )

        print(response.answer)

    Note: OPENAI_API_KEY environment variable must be set
    """

    def __init__(self, model: str = "gpt-4o-mini"):
        """
        Initialize RAG Engine

        Args:
            model: OpenAI model name
        """
        self.config = get_config()
        self.model = model
        self.query_engine = QueryEngine()

        # Check API key
        self.api_key = self.config.openai_api_key
        if not self.api_key:
            logger.warning("OPENAI_API_KEY not set; RAG functionality will be unavailable")

    def ask(
        self,
        question: str,
        team: str = None,
        player: str = None,
        game_date: str = None,
        top_k: int = 10,
    ) -> RAGResponse:
        """
        Answer question

        Full RAG process:
        1. Retrieve relevant evidence
        2. Build prompt
        3. Call LLM
        4. Return response

        Args:
            question: question string
            team: team filter
            player: player filter
            game_date: date filter
            top_k: number of evidence to retrieve

        Returns:
            RAGResponse: response containing the answer and evidence
        """
        # 1. Retrieve evidence
        logger.info(f"Retrieving evidence: {question[:50]}...")
        evidence = self.query_engine.query(
            question=question,
            team=team,
            player=player,
            game_date=game_date,
            top_k=top_k,
        )

        if not evidence:
            return RAGResponse(
                answer="Sorry, no relevant information was found to answer the question.",
                evidence=[],
                model=self.model,
            )

        # 2. Build prompt
        prompt = build_prompt(
            question=question,
            evidence=evidence,
            team=team,
            player=player,
            game_date=game_date,
        )

        # 3. Call LLM
        answer, tokens = self._call_llm(prompt)

        return RAGResponse(
            answer=answer,
            evidence=evidence,
            model=self.model,
            tokens_used=tokens,
        )

    def assess_team(
        self,
        team: str,
        game_date: str,
        top_k: int = 15,
    ) -> Dict[str, Any]:
        """
        Assess player status for a team

        Returns structured player assessment JSON

        Args:
            team: team code
            game_date: game date
            top_k: number of evidence to retrieve

        Returns:
            dict: player assessment results
        """
        # Retrieve evidence
        question = f"What is the injury status and availability for {team} players for the game on {game_date}?"

        evidence = self.query_engine.query(
            question=question,
            team=team,
            game_date=game_date,
            top_k=top_k,
        )

        if not evidence:
            return {
                "team": team,
                "game_date": game_date,
                "assessments": [],
                "notes": "No relevant injury information found",
            }

        # Build assessment prompt
        prompt = build_assessment_prompt(team, game_date, evidence)

        # Call LLM
        response, _ = self._call_llm(prompt)

        # Parse JSON
        assessment = self._parse_json_response(response)

        return assessment

    def _call_llm(self, prompt: str) -> tuple:
        """
        Call LLM

        Args:
            prompt: user prompt

        Returns:
            tuple: (response text, token count)
        """
        if not self.api_key:
            return (
                "Error: OPENAI_API_KEY is not set. Please set it in your .env file.",
                0
            )

        try:
            # Use OpenAI API - new openai package syntax
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key)

            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Lower temp for more consistent output
                max_tokens=2000,
            )

            answer = response.choices[0].message.content
            tokens = response.usage.total_tokens if response.usage else 0

            return answer, tokens

        except ImportError:
            return (
                "Error: The openai package is not installed. Please run pip install openai.",
                0
            )
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return (f"LLM call failed: {e}", 0)

    def _parse_json_response(self, response: str) -> dict:
        """
        Parse JSON from LLM response

        The LLM may add text around the JSON,
        so we need to extract just the JSON portion.

        Args:
            response: LLM response string

        Returns:
            dict: parsed JSON
        """
        try:
            # Try direct parse
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Try to find JSON block
        # Match ```json ... ``` or { ... }
        json_patterns = [
            r"```json\s*([\s\S]*?)\s*```",  # ```json ... ```
            r"```\s*([\s\S]*?)\s*```",      # ``` ... ```
            r"(\{[\s\S]*\})",               # { ... }
        ]

        for pattern in json_patterns:
            match = re.search(pattern, response)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue

        # Could not parse
        logger.warning("Could not parse JSON from LLM response")
        return {
            "error": "Could not parse JSON",
            "raw_response": response,
        }


def generate_answer(
    question: str,
    team: str = None,
    player: str = None,
    top_k: int = 10,
) -> str:
    """
    Convenience function: Generate answer

    Args:
        question: question string
        team: team
        player: player
        top_k: number of evidence to retrieve

    Returns:
        str: answer text

    Example usage:
        from src.rag import generate_answer

        answer = generate_answer(
            "Is LeBron playing tonight?",
            team="LAL"
        )
        print(answer)
    """
    engine = RAGEngine()
    response = engine.ask(
        question=question,
        team=team,
        player=player,
        top_k=top_k,
    )
    return response.answer


def retrieval_only(
    question: str,
    team: str = None,
    player: str = None,
    top_k: int = 10,
) -> List[QueryResult]:
    """
    Convenience function: retrieval only, no LLM call

    Used for testing retrieval or in cases where LLM is not needed

    Args:
        question: question string
        team: team
        player: player
        top_k: number of evidence to retrieve

    Returns:
        List[QueryResult]: retrieval results
    """
    engine = QueryEngine()
    return engine.query(
        question=question,
        team=team,
        player=player,
        top_k=top_k,
    )

