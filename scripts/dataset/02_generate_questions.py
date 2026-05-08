#!/usr/bin/env python3
"""
02_generate_questions.py - Phase 2: Question 生成

讀取 Phase 1 產出的 train_contexts.jsonl，依 (player, metric) 分組，
對每組產出單一問題，並彙整該 player+metric 下所有 filter 的 context。

產出 train_questions.jsonl，每行含 question + contexts（該 player+metric 的全部 context），供 Phase 3 使用。

使用方式：
    # 從專案根目錄執行
    python scripts/dataset/02_generate_questions.py

    # 或指定輸入/輸出
    python scripts/dataset/02_generate_questions.py --input data/train_contexts.jsonl --output data/train_questions.jsonl
"""

import argparse
import json
import sys
from pathlib import Path

# 專案根目錄
project_root = Path(__file__).resolve().parent.parent.parent

# 預設路徑
DEFAULT_INPUT_PATH = project_root / "data" / "train_contexts.jsonl"
DEFAULT_OUTPUT_PATH = project_root / "data" / "train_questions.jsonl"

# metric 對應的顯示名稱（用於問題中）
METRIC_DISPLAY = {
    "points": "points",
    "assists": "assists",
    "rebounds": "rebounds",
    "pra": "PRA",
}


def format_question(player: str, threshold: float, metric: str) -> str:
    """
    依模板產出問題：Should I bet {player} over/under {threshold} {metric}?
    """
    display_metric = METRIC_DISPLAY.get(metric, metric)
    return f"Should I bet {player} over/under {threshold} {display_metric}?"


def main():
    parser = argparse.ArgumentParser(description="Phase 2: 從 context 產出 questions")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Phase 1 產出的 context JSONL 路徑",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="輸出 questions JSONL 路徑",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"❌ 輸入檔案不存在: {args.input}")
        print("   請先執行 Phase 1: python scripts/dataset/01_sample_contexts.py")
        sys.exit(1)

    # 1. 讀取所有 context
    contexts: list[dict] = []
    with open(args.input, "r", encoding="utf-8") as fin:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                contexts.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"⚠️ 跳過無效 JSON: {e}")
                continue

    # 2. 依 (player, metric) 分組
    groups: dict[tuple[str, str], list[dict]] = {}
    for ctx in contexts:
        player = ctx.get("player", "")
        metric = ctx.get("metric", "points")
        key = (player, metric)
        if key not in groups:
            groups[key] = []
        groups[key].append(ctx)

    # 3. 每組產出 1 題，threshold 取自「全部場次」context，若無則取 n_games 最大者
    count = 0
    with open(args.output, "w", encoding="utf-8") as fout:
        for (player, metric), group_contexts in groups.items():
            # 選 threshold：優先 filter 為空（全部場次），否則取 n_games 最大
            def _sort_key(c: dict) -> tuple:
                has_all = 1 if c.get("filter") == {} else 0
                n = c.get("stats", {}).get("n_games", 0)
                return (has_all, n)

            chosen = max(group_contexts, key=_sort_key)
            threshold = chosen.get("threshold", 0)

            question = format_question(player, threshold, metric)
            record = {
                "question": question,
                "contexts": group_contexts,
            }
            fout.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1

    print(f"✅ 完成！產出 {count} 題至 {args.output}")


if __name__ == "__main__":
    main()
