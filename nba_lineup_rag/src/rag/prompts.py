"""
prompts.py - Prompt templates module

This module defines:
1. System prompt - sets the LLM's role and task
2. User prompt template - combines the question and evidence
3. Output format requirements

Naming:
- SYSTEM_PROMPT: the system prompt constant
- build_prompt(): builds the complete user prompt
- format_evidence(): formats evidence chunks
"""

from typing import List, Dict, Any

from src.vectordb.query import QueryResult

# System Prompt
# This prompt defines the LLM's role and behavioral guidelines
SYSTEM_PROMPT = """You are a professional NBA player status analysis assistant. Your task is to answer questions about player injury status, probability of playing, and estimated playing time based on the provided evidence.

## Rules
1. Answer only based on the provided evidence; do not make up information
2. If the evidence is insufficient to answer the question, clearly state "Unable to determine based on current information"
3. When citing evidence, indicate the source (e.g., [1], [2])
4. Use appropriate wording (such as "possible", "expected", "tends to") for uncertain information

## Injury Status Explanation
- Out: Confirmed not playing
- Doubtful: Very unlikely to play (about 25% chance)
- Questionable: Uncertain (about 50% chance)
- Probable: Very likely to play (about 75% chance)
- Available: Available to play
- GTD (Game-Time Decision): Decided before game

## Answer format
Please answer clearly and in a structured way, including:
1. Direct answer to the question
2. Supporting evidence (with citations)
3. Confidence level (high/medium/low)
4. Any noteworthy uncertainties
"""

def format_evidence(results: List[QueryResult], max_chars: int = 6000) -> str:
    """
    Formats the query results as an evidence text block.
    
    Args:
        results: List of QueryResult
        max_chars: Maximum characters allowed (prevent context-window overflow)
    
    Returns:
        str: Formatted evidence text
    
    Example format:
        [1] (nba_injuries_pages, 2026-01-27)
        TEAM: LAL
        PLAYER: LeBron James
        STATUS: Questionable
        ...
        
        [2] (nba_news, 2026-01-27)
        LeBron James practiced today but...
    """
    if not results:
        return "(No relevant evidence found)"
    
    lines = []
    total_chars = 0
    
    for i, r in enumerate(results, 1):
        # Build a single evidence entry
        meta = r.metadata
        source = r.collection
        date = meta.get("published_at", "unknown")[:10]  # Only date part
        
        # Header line
        evidence_header = f"[{i}] ({source}, {date})"
        
        # If there is a title
        title = meta.get("title", "")
        if title:
            evidence_header += f"\nTitle: {title}"
        
        # Content
        content = r.text
        
        # Combine
        evidence_text = f"{evidence_header}\n{content}\n"
        
        # Check length limit
        if total_chars + len(evidence_text) > max_chars:
            # Truncate current evidence
            remaining = max_chars - total_chars - 50
            if remaining > 100:
                truncated = content[:remaining] + "...(truncated)"
                evidence_text = f"{evidence_header}\n{truncated}\n"
                lines.append(evidence_text)
            lines.append(f"\n({len(results) - i} evidence entries omitted due to length limit)")
            break
        
        lines.append(evidence_text)
        total_chars += len(evidence_text)
    
    return "\n".join(lines)

def build_prompt(
    question: str,
    evidence: List[QueryResult],
    team: str = None,
    player: str = None,
    game_date: str = None,
) -> str:
    """
    Builds the user prompt
    
    Args:
        question: User question
        evidence: Retrieved evidence
        team: Team (for additional context)
        player: Player
        game_date: Game date
    
    Returns:
        str: Complete user prompt
    
    Example usage:
        prompt = build_prompt(
            question="Is LeBron playing tonight?",
            evidence=query_results,
            team="LAL",
            player="LeBron James"
        )
    """
    # Build context section
    context_parts = []
    if team:
        context_parts.append(f"Team: {team}")
    if player:
        context_parts.append(f"Player: {player}")
    if game_date:
        context_parts.append(f"Game date: {game_date}")
    
    context = " | ".join(context_parts) if context_parts else ""
    
    # Format evidence
    evidence_text = format_evidence(evidence)
    
    # Compose full prompt
    prompt = f"""## Question
{question}

"""
    if context:
        prompt += f"""## Context
{context}

"""
    prompt += f"""## Evidence
The following is relevant information retrieved from the database. Please answer the question based on this evidence:

{evidence_text}

## Please Answer
Please answer the question based on the above evidence. If the evidence is insufficient, please state so.
"""
    
    return prompt

def build_assessment_prompt(
    team: str,
    game_date: str,
    evidence: List[QueryResult],
) -> str:
    """
    Builds a player assessment prompt (structured output)
    
    This prompt asks the LLM to output a specific JSON format
    
    Args:
        team: Team code
        game_date: Game date
        evidence: Retrieved evidence
    
    Returns:
        str: Prompt string
    """
    evidence_text = format_evidence(evidence)
    
    prompt = f"""## Task
Based on the following evidence, assess the status of each player on team {team} in the game on {game_date}.

## Evidence
{evidence_text}

## Output Format
Please output the assessment in JSON format:

```json
{{
  "team": "{team}",
  "game_date": "{game_date}",
  "assessments": [
    {{
      "player": "Player name",
      "p_play": 0.85,  // Probability of playing (0-1)
      "p_start": 0.60, // Probability of starting (0-1)
      "minutes_range": [28, 34],  // Expected playing minutes range
      "confidence": "high|medium|low",  // Assessment confidence
      "status": "probable|questionable|doubtful|out|healthy",
      "injury": "Injury description (if any)",
      "evidence": [1, 2]  // Referenced evidence numbers
    }}
  ],
  "notes": "Any additional notes"
}}
```

Output only the JSON, no other text.
"""
    
    return prompt

