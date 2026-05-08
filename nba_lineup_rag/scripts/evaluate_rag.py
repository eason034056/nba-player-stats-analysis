#!/usr/bin/env python3
"""
evaluate_rag.py - RAG Evaluation Script

This script is used to run the evaluation tasks in Part 2:
1. For 5 test questions, compare the outputs of 4 methods
2. Automatically save results to JSON and Markdown files
3. Provides a convenient command line interface

The 4 evaluation methods:
- llm_only: LLM only (no RAG) - Baseline
- simple_rag: Simple RAG (vector retrieval + LLM)
- hyde: HyDE RAG (hypothetical document embedding)
- rerank: Reranking RAG (two-stage retrieval)

Usage examples:
    # Run all evaluations
    python scripts/evaluate_rag.py

    # Evaluate a specific question only
    python scripts/evaluate_rag.py --question "Is LeBron playing tonight?"

    # Use specific methods only
    python scripts/evaluate_rag.py --methods llm_only simple_rag

Output files:
- outputs/evaluation_results.json: Full result JSON
- outputs/evaluation_report.md: Markdown report
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass, asdict
import argparse

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_config
from src.logging_utils import get_logger

logger = get_logger(__name__)

# Default 5 test questions
# These questions are designed to be challenging for pure LLM, requiring up-to-date information
DEFAULT_TEST_QUESTIONS = [
    {
        "id": 1,
        "question": "Is Kevin Durant playing tonight against the Pacers?",
        "team": "HOU",
        "player": "Kevin Durant",
        "description": "Needs real-time injury info for Rockets star",
    },
    {
        "id": 2,
        "question": "What is Brandon Ingram’s injury status today?",
        "team": "TOR",
        "player": "Brandon Ingram",
        "description": "Needs latest status update for Hornets key player",
    },
    {
        "id": 3,
        "question": "Which Timberwolves players are currently listed as questionable or out for tonight?",
        "team": "MIN",
        "player": None,
        "description": "Requires retrieval of information on multiple players",
    },
    {
        "id": 4,
        "question": "What injuries have affected the Grizzlies going into tonight’s game?",
        "team": "MEM",
        "player": None,
        "description": "Needs overall team injury status",
    },
    {
        "id": 5,
        "question": "Who are the key NBA players dealing with injuries and questionable statuses for tonight’s slate of games?",
        "team": None,
        "player": None,
        "description": "Needs cross-team summary info for Feb 2 games",
    },
]

@dataclass
class EvaluationResult:
    """Single evaluation result"""
    question: str
    team: str
    player: str
    description: str
    method: str
    answer: str
    sources_count: int
    retrieval_scores: List[float]
    timestamp: str
    error: str = None

    def to_dict(self) -> dict:
        return asdict(self)

class RAGEvaluator:
    """
    RAG Evaluator

    Automatically runs comparative evaluation for multiple RAG methods
    """

    def __init__(self):
        """Initialize the evaluator"""
        self.config = get_config()
        self.output_dir = Path(self.config.project_root) / "outputs"
        self.output_dir.mkdir(exist_ok=True)

        # Lazy load individual RAG modules
        self._langchain_rag = None
        self._hyde_retriever = None
        self._reranked_rag = None

    @property
    def langchain_rag(self):
        """Lazy load LangChain RAG"""
        if self._langchain_rag is None:
            from src.rag.langchain_rag import LangChainRAG
            self._langchain_rag = LangChainRAG()
        return self._langchain_rag

    @property
    def hyde_retriever(self):
        """Lazy load HyDE Retriever"""
        if self._hyde_retriever is None:
            from src.rag.hyde import HyDERetriever
            self._hyde_retriever = HyDERetriever()
        return self._hyde_retriever

    @property
    def reranked_rag(self):
        """Lazy load Reranked RAG"""
        if self._reranked_rag is None:
            from src.rag.reranker import RerankedRAG
            self._reranked_rag = RerankedRAG()
        return self._reranked_rag

    def evaluate_llm_only(self, question: str, team: str = None, player: str = None) -> Dict:
        """Evaluate LLM Only method"""
        logger.info(f"[LLM Only] Evaluating: {question[:50]}...")
        try:
            result = self.langchain_rag.query_llm_only(question, team=team, player=player)
            return {
                "answer": result.answer,
                "sources_count": 0,
                "retrieval_scores": [],
                "error": None,
            }
        except Exception as e:
            logger.error(f"LLM Only evaluation failed: {e}")
            return {"answer": "", "sources_count": 0, "retrieval_scores": [], "error": str(e)}

    def evaluate_simple_rag(self, question: str, team: str = None, player: str = None) -> Dict:
        """Evaluate Simple RAG method"""
        logger.info(f"[Simple RAG] Evaluating: {question[:50]}...")
        try:
            result = self.langchain_rag.query_simple_rag(question, team=team, player=player)
            return {
                "answer": result.answer,
                "sources_count": len(result.sources),
                "retrieval_scores": result.retrieval_scores,
                "error": None,
            }
        except Exception as e:
            logger.error(f"Simple RAG evaluation failed: {e}")
            return {"answer": "", "sources_count": 0, "retrieval_scores": [], "error": str(e)}

    def evaluate_hyde(self, question: str, team: str = None, player: str = None) -> Dict:
        """Evaluate HyDE method"""
        logger.info(f"[HyDE] Evaluating: {question[:50]}...")
        try:
            result = self.hyde_retriever.query(question, team=team, player=player)
            return {
                "answer": result.answer,
                "sources_count": len(result.sources),
                "retrieval_scores": result.retrieval_scores,
                "error": None,
            }
        except Exception as e:
            logger.error(f"HyDE evaluation failed: {e}")
            return {"answer": "", "sources_count": 0, "retrieval_scores": [], "error": str(e)}

    def evaluate_rerank(self, question: str, team: str = None, player: str = None) -> Dict:
        """Evaluate Reranking method"""
        logger.info(f"[Rerank] Evaluating: {question[:50]}...")
        try:
            result = self.reranked_rag.query(question, team=team, player=player)
            return {
                "answer": result.answer,
                "sources_count": len(result.sources),
                "retrieval_scores": result.retrieval_scores,
                "error": None,
            }
        except Exception as e:
            logger.error(f"Rerank evaluation failed: {e}")
            return {"answer": "", "sources_count": 0, "retrieval_scores": [], "error": str(e)}

    def run_evaluation(
        self,
        questions: List[Dict] = None,
        methods: List[str] = None,
    ) -> List[EvaluationResult]:
        """
        Run full evaluation

        Args:
            questions: list of test questions (default is DEFAULT_TEST_QUESTIONS)
            methods: list of methods to evaluate (default all)

        Returns:
            List[EvaluationResult]: all evaluation results
        """
        questions = questions or DEFAULT_TEST_QUESTIONS
        methods = methods or ["llm_only", "simple_rag", "hyde", "rerank"]

        # Method function mapping
        method_funcs = {
            "llm_only": self.evaluate_llm_only,
            "simple_rag": self.evaluate_simple_rag,
            "hyde": self.evaluate_hyde,
            "rerank": self.evaluate_rerank,
        }

        results = []
        timestamp = datetime.now().isoformat()

        total = len(questions) * len(methods)
        current = 0

        for q_info in questions:
            question = q_info["question"]
            team = q_info.get("team")
            player = q_info.get("player")
            description = q_info.get("description", "")

            print(f"\n{'='*60}")
            print(f"Question: {question}")
            print(f"{'='*60}")

            for method in methods:
                current += 1
                print(f"\n[{current}/{total}] Method: {method}")

                func = method_funcs.get(method)
                if not func:
                    logger.warning(f"Unknown method: {method}")
                    continue

                eval_result = func(question, team, player)

                result = EvaluationResult(
                    question=question,
                    team=team or "",
                    player=player or "",
                    description=description,
                    method=method,
                    answer=eval_result["answer"],
                    sources_count=eval_result["sources_count"],
                    retrieval_scores=eval_result["retrieval_scores"],
                    timestamp=timestamp,
                    error=eval_result.get("error"),
                )

                results.append(result)

                # Show brief result
                answer_preview = result.answer[:200] + "..." if len(result.answer) > 200 else result.answer
                print(f"   Answer: {answer_preview}")
                print(f"   Sources: {result.sources_count}")

        return results

    def save_results(
        self,
        results: List[EvaluationResult],
        filename_prefix: str = "evaluation",
    ):
        """
        Save evaluation results

        Args:
            results: list of evaluation results
            filename_prefix: filename prefix
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save JSON
        json_path = self.output_dir / f"{filename_prefix}_results_{timestamp}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                [r.to_dict() for r in results],
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"\n✅ JSON results saved: {json_path}")

        # Generate and save Markdown report
        md_path = self.output_dir / f"{filename_prefix}_report_{timestamp}.md"
        markdown = self._generate_markdown_report(results)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown)
        print(f"✅ Markdown report saved: {md_path}")

        return json_path, md_path

    def _generate_markdown_report(self, results: List[EvaluationResult]) -> str:
        """Generate Markdown report"""
        lines = [
            "# RAG Evaluation Report",
            "",
            f"**Generated At**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Evaluation Methods",
            "",
            "| Method | Description |",
            "|--------|-------------|",
            "| LLM Only | LLM only, no retrieval (Baseline) |",
            "| Simple RAG | Vector retrieval + LLM to answer |",
            "| HyDE | Generate hypothetical docs, then retrieve by embedding |",
            "| Rerank | Two-stage: vector retrieval then Cross-Encoder rerank |",
            "",
            "---",
            "",
        ]

        # Group by question
        questions = {}
        for r in results:
            if r.question not in questions:
                questions[r.question] = {
                    "description": r.description,
                    "team": r.team,
                    "player": r.player,
                    "methods": {},
                }
            questions[r.question]["methods"][r.method] = r

        # Generate report per question
        for i, (question, data) in enumerate(questions.items(), 1):
            lines.extend([
                f"## Question {i}",
                "",
                f"**Question**: {question}",
                "",
                f"**Description**: {data['description']}",
                "",
            ])

            if data["team"]:
                lines.append(f"**Team**: {data['team']}")
            if data["player"]:
                lines.append(f"**Player**: {data['player']}")
            lines.append("")

            # Results per method
            method_order = ["llm_only", "simple_rag", "hyde", "rerank"]
            method_names = {
                "llm_only": "A. LLM Only (no RAG)",
                "simple_rag": "B. Simple RAG",
                "hyde": "C. HyDE RAG",
                "rerank": "D. Reranking RAG",
            }

            for method in method_order:
                if method not in data["methods"]:
                    continue

                r = data["methods"][method]

                lines.extend([
                    f"### {method_names[method]}",
                    "",
                ])

                if r.error:
                    lines.extend([
                        f"**Error**: {r.error}",
                        "",
                    ])
                else:
                    lines.extend([
                        "**Answer**:",
                        "",
                        "> " + r.answer.replace("\n", "\n> "),
                        "",
                        f"**Number of Sources**: {r.sources_count}",
                        "",
                    ])

            lines.extend([
                "### Comparative Analysis",
                "",
                "| Method | Sources | Evaluation |",
                "|--------|---------|------------|",
            ])

            for method in method_order:
                if method not in data["methods"]:
                    continue
                r = data["methods"][method]
                # Here user can fill in their own evaluation, or leave blank
                lines.append(f"| {method_names[method].split('. ')[1]} | {r.sources_count} | _TBD_ |")

            lines.extend([
                "",
                "---",
                "",
            ])

        return "\n".join(lines)

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="RAG evaluation script - Compare different RAG methods"
    )

    parser.add_argument(
        "--question",
        type=str,
        help="Evaluate a single question only",
    )

    parser.add_argument(
        "--methods",
        type=str,
        nargs="+",
        choices=["llm_only", "simple_rag", "hyde", "rerank"],
        help="Specify methods to evaluate",
    )

    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not save results to files",
    )

    args = parser.parse_args()

    # Initialize evaluator
    evaluator = RAGEvaluator()

    # Prepare questions
    if args.question:
        questions = [{
            "question": args.question,
            "team": None,
            "player": None,
            "description": "Custom question",
        }]
    else:
        questions = DEFAULT_TEST_QUESTIONS

    # Run evaluation
    print("\n" + "="*60)
    print("NBA RAG Evaluation")
    print("="*60)
    print(f"Number of Questions: {len(questions)}")
    print(f"Methods: {args.methods or ['llm_only', 'simple_rag', 'hyde', 'rerank']}")
    print("="*60)

    results = evaluator.run_evaluation(
        questions=questions,
        methods=args.methods,
    )

    # Save results
    if not args.no_save:
        evaluator.save_results(results)

    print("\n✅ Evaluation Done!")


if __name__ == "__main__":
    main()
