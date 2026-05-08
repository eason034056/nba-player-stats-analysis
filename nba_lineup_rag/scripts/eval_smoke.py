#!/usr/bin/env python3
"""
eval_smoke.py - Smoke Test Script

This script is used to quickly verify if the retrieval system is working properly.

Usage:
    python scripts/eval_smoke.py
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.logging_utils import get_logger
from src.vectordb.query import QueryEngine
from src.vectordb.collections import get_collection_manager

logger = get_logger("eval_smoke")


# Predefined smoke test queries
TEST_QUERIES = [
    {
        "question": "Who is injured on the Lakers?",
        "team": "LAL",
        "expected_keywords": ["lakers", "injury", "out", "questionable"],
    },
    {
        "question": "Is there any minutes restriction for any player?",
        "team": None,
        "expected_keywords": ["minutes", "restriction", "limited"],
    },
    {
        "question": "Which players are questionable for tonight?",
        "team": None,
        "expected_keywords": ["questionable"],
    },
    {
        "question": "What is the latest injury update?",
        "team": None,
        "expected_keywords": ["injury", "update", "status"],
    },
    {
        "question": "Who will not play in the next game?",
        "team": None,
        "expected_keywords": ["out", "not play", "ruled out"],
    },
]


def run_smoke_test():
    """
    Run smoke test

    Checks:
    1. Collections exist
    2. Each test query returns results
    3. Results contain expected keywords
    """
    logger.info("=== Starting smoke test ===\n")
    
    # Check collections
    manager = get_collection_manager()
    stats = manager.get_stats()
    
    logger.info("Collections status:")
    total_docs = 0
    for name, info in stats.items():
        count = info.get("count", 0)
        total_docs += count
        status = "✓" if count > 0 else "✗ (empty)"
        logger.info(f"  {name}: {count} chunks {status}")
    
    if total_docs == 0:
        logger.warning("\nWarning: All collections are empty!")
        logger.warning("Please run python scripts/ingest_all.py to fetch data\n")
        return
    
    # Run test queries
    engine = QueryEngine()
    
    passed = 0
    failed = 0
    
    logger.info("\nTest queries:")
    
    for i, test in enumerate(TEST_QUERIES, 1):
        question = test["question"]
        team = test.get("team")
        expected = test.get("expected_keywords", [])
        
        logger.info(f"\n[{i}] {question}")
        if team:
            logger.info(f"    Filter: team={team}")
        
        try:
            results = engine.query(
                question=question,
                team=team,
                top_k=5
            )
            
            if not results:
                logger.warning(f"    Result: No result ✗")
                failed += 1
                continue
            
            # Check if expected keywords are found
            all_text = " ".join([r.text.lower() for r in results])
            found_keywords = [kw for kw in expected if kw.lower() in all_text]
            
            if len(found_keywords) >= len(expected) // 2:  # At least half of the keywords found
                logger.info(f"    Result: {len(results)} result(s) ✓")
                logger.info(f"    Found keywords: {found_keywords}")
                passed += 1
            else:
                logger.warning(f"    Result: {len(results)} result(s), but insufficient keyword matches △")
                logger.warning(f"    Expected: {expected}, found: {found_keywords}")
                passed += 0.5
            
            # Show preview of first result
            if results:
                preview = results[0].text[:100].replace("\n", " ")
                logger.info(f"    Preview: {preview}...")
                
        except Exception as e:
            logger.error(f"    Error: {e} ✗")
            failed += 1
    
    # Summary
    total = len(TEST_QUERIES)
    pass_rate = passed / total * 100
    
    logger.info("\n" + "=" * 50)
    logger.info(f"Test completed: {passed}/{total} passed ({pass_rate:.1f}%)")
    
    if pass_rate >= 60:
        logger.info("Status: ✓ Pass")
    else:
        logger.warning("Status: ✗ Needs inspection")
    
    logger.info("=" * 50)


if __name__ == "__main__":
    run_smoke_test()

