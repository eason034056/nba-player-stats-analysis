#!/usr/bin/env python3
"""
query_cli.py - Command-line Query Tool

This script provides a command-line interface for querying the vector database.

Usage:
    # Basic query
    python scripts/query_cli.py --q "Is LeBron playing tonight?"
    
    # With filter conditions
    python scripts/query_cli.py --team LAL --q "injury update" --k 5
    
    # Interactive mode
    python scripts/query_cli.py --interactive

Naming conventions:
- main(): program entry point
- interactive_mode(): interactive query mode
- format_results(): result formatting output
"""

import argparse
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.vectordb.query import QueryEngine, QueryResult
from src.logging_utils import get_logger
from typing import List

logger = get_logger("query_cli")


def format_results(results: List[QueryResult], verbose: bool = False) -> str:
    """
    Format the query results as a readable string.
    
    Args:
        results: List of query results
        verbose: Whether to show detailed information
    
    Returns:
        str: Formatted string
    """
    if not results:
        return "No relevant results found."
    
    lines = [f"\nFound {len(results)} relevant result(s):\n"]
    lines.append("=" * 60)
    
    for i, r in enumerate(results, 1):
        # Basic information
        lines.append(f"\n[{i}] Score: {r.score:.4f} | Source: {r.collection}")
        
        # Metadata
        meta = r.metadata
        if meta.get("team"):
            lines.append(f"    Team: {meta.get('team')}")
        if meta.get("player_names"):
            lines.append(f"    Player(s): {', '.join(meta.get('player_names', []))}")
        if meta.get("title"):
            lines.append(f"    Title: {meta.get('title')[:60]}...")
        if meta.get("published_at"):
            lines.append(f"    Date: {meta.get('published_at')}")
        
        # Content preview
        text_preview = r.text[:200].replace("\n", " ")
        lines.append(f"    Content: {text_preview}...")
        
        # Detailed mode shows full content
        if verbose:
            lines.append(f"\n    --- Full Content ---")
            lines.append(f"    {r.text}")
            lines.append(f"    --- End ---\n")
        
        lines.append("-" * 60)
    
    return "\n".join(lines)


def single_query(
    question: str,
    team: str = None,
    player: str = None,
    top_k: int = 10,
    verbose: bool = False,
):
    """
    Execute a single query
    
    Args:
        question: The query question
        team: Team filter
        player: Player filter
        top_k: Number of results to return
        verbose: Verbose mode
    """
    engine = QueryEngine()
    
    print(f"\nQuery: {question}")
    if team:
        print(f"Team filter: {team}")
    if player:
        print(f"Player filter: {player}")
    
    results = engine.query(
        question=question,
        team=team,
        player=player,
        top_k=top_k,
    )
    
    output = format_results(results, verbose)
    print(output)
    
    return results


def interactive_mode():
    """
    Interactive query mode
    
    The user can enter queries continuously. Enter 'exit' or 'quit' to exit.
    """
    engine = QueryEngine()
    
    print("\n" + "=" * 60)
    print("NBA Lineup RAG - Interactive Query")
    print("=" * 60)
    print("Commands:")
    print("  Enter your question directly to query")
    print("  /team LAL - set team filter")
    print("  /player LeBron - set player filter")
    print("  /clear - clear all filters")
    print("  /exit or /quit - exit")
    print("=" * 60 + "\n")
    
    # Current filters
    current_team = None
    current_player = None
    
    while True:
        try:
            # Show prompt with current filters
            prompt_parts = ["Query"]
            if current_team:
                prompt_parts.append(f"team={current_team}")
            if current_player:
                prompt_parts.append(f"player={current_player}")
            prompt = f"[{' | '.join(prompt_parts)}]> "
            
            user_input = input(prompt).strip()
            
            if not user_input:
                continue
            
            # Handle commands
            if user_input.startswith("/"):
                cmd = user_input[1:].lower()
                
                if cmd in ["exit", "quit", "q"]:
                    print("Goodbye!")
                    break
                
                elif cmd.startswith("team "):
                    current_team = cmd[5:].strip().upper()
                    print(f"Team filter set: {current_team}")
                    continue
                
                elif cmd.startswith("player "):
                    current_player = cmd[7:].strip()
                    print(f"Player filter set: {current_player}")
                    continue
                
                elif cmd == "clear":
                    current_team = None
                    current_player = None
                    print("All filters cleared.")
                    continue
                
                else:
                    print(f"Unknown command: {cmd}")
                    continue
            
            # Execute query
            results = engine.query(
                question=user_input,
                team=current_team,
                player=current_player,
                top_k=10,
            )
            
            output = format_results(results)
            print(output)
            
        except KeyboardInterrupt:
            print("\n\nUse /exit to quit.")
        except EOFError:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


def main():
    """
    Program entry point
    """
    parser = argparse.ArgumentParser(
        description="NBA Lineup RAG - Command-line Query Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Basic query
    python scripts/query_cli.py --q "Is LeBron playing tonight?"
    
    # With filter
    python scripts/query_cli.py --team LAL --q "injury update" --k 5
    
    # Interactive mode
    python scripts/query_cli.py --interactive
        """
    )
    
    # Query parameters
    parser.add_argument(
        "--q", "--query",
        type=str,
        help="Query question"
    )
    
    parser.add_argument(
        "--team",
        type=str,
        help="Team filter (e.g., LAL, BOS)"
    )
    
    parser.add_argument(
        "--player",
        type=str,
        help="Player filter"
    )
    
    parser.add_argument(
        "--date",
        type=str,
        help="Date filter (YYYY-MM-DD)"
    )
    
    parser.add_argument(
        "--k", "--top-k",
        type=int,
        default=10,
        help="Number of results to return (default: 10)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed content"
    )
    
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Enter interactive mode"
    )
    
    args = parser.parse_args()
    
    # Interactive mode
    if args.interactive:
        interactive_mode()
        return
    
    # Single query
    if args.q:
        single_query(
            question=args.q,
            team=args.team,
            player=args.player,
            top_k=args.k,
            verbose=args.verbose,
        )
    else:
        # No query provided, show help
        parser.print_help()


if __name__ == "__main__":
    main()

