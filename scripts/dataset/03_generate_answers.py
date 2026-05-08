#!/usr/bin/env python3
"""
03_generate_answers.py - Phase 3: Answer 生成（OpenAI）

使用 OpenAI API（gpt-4o-mini）為 train_questions.jsonl 中的每題生成
Tree-of-Thought 結構化答案，產出 train_full.jsonl 供 LoRA 微調使用。

實作要點（依 plan Phase 3 與第八點建議）：
1. 讀取 train_questions.jsonl，使用 contexts 陣列（非 context）
2. Prompt 將 contexts 序列化後傳給模型，供其參考多種 filter 的統計
3. 輸出符合 Schema 的 JSON：decision, confidence, reasoning.tree_of_thought, summary
4. 批次生成：rate limit、retry、logging
5. 品質過濾：驗證 JSON、過濾 decision 缺失或 reasoning 過短的樣本

使用方式：
    # 從專案根目錄執行（需設定 OPENAI_API_KEY）
    python scripts/dataset/03_generate_answers.py

    # 指定輸入/輸出、模型、限制筆數
    python scripts/dataset/03_generate_answers.py --input data/train_questions.jsonl --output data/train_full.jsonl --model gpt-4o-mini --limit 10
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# 專案根目錄（scripts/dataset 的上兩層）
project_root = Path(__file__).resolve().parent.parent.parent

# 載入 .env（讓 OPENAI_API_KEY 等變數生效）
try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
except ImportError:
    pass  # 無 python-dotenv 時略過，改用環境變數

# 預設路徑
DEFAULT_INPUT_PATH = project_root / "data" / "train_questions.jsonl"
DEFAULT_OUTPUT_PATH = project_root / "data" / "train_full.jsonl"

# 輸出 JSON Schema（與 plan 二、輸出結構化 Schema 一致）
OUTPUT_SCHEMA = {
    "decision": "over | under | avoid",
    "confidence": "0.0 - 1.0",
    "reasoning": {
        "tree_of_thought": [
            {"step": 1, "branch": "sample_stats|lineup_teammate|synthesis", "thought": "...", "conclusion": "..."},
        ],
    },
    "summary": "一句話結論",
}

# System prompt：定義模型角色與輸出格式
SYSTEM_PROMPT = """You are an expert NBA player data analyst. Your task is to analyze betting questions (over/under) using historical player statistics.

## Tree of Thought Reasoning Framework

Build your reasoning as a tree with these main branches (evaluate each, then synthesize):

1. **Sample & Statistics Branch**: For each context filter (all games, last N games, starter vs bench, with/without star teammates), assess:
   - n_games: Is sample size sufficient? (n < 10 → low weight)
   - p_over, p_under, mean, std: Which context favors over vs under?
   - Conflict between contexts → note uncertainty

2. **Lineup/Teammate Branch**: How does starter vs bench, or with/without star teammates, change the stats? Does lineup context support or contradict the main trend?

3. **Risk & Synthesis Branch**: Given the above, what is the net signal? If branches conflict or sample is weak → prefer "avoid".

## Output Format (JSON only, no markdown)

{
  "decision": "over" | "under" | "avoid",
  "confidence": 0.0 to 1.0,
  "reasoning": {
    "tree_of_thought": [
      {"step": 1, "branch": "sample_stats", "thought": "...", "conclusion": "..."},
      {"step": 2, "branch": "lineup_teammate", "thought": "...", "conclusion": "..."},
      {"step": 3, "branch": "synthesis", "thought": "...", "conclusion": "..."}
    ]
  },
  "summary": "One-sentence conclusion"
}

Each step must have: branch (which dimension), thought (your analysis), conclusion (what this branch implies for the decision).
Respond with ONLY valid JSON, no markdown or extra text."""


def build_user_prompt(question: str, contexts: list[dict]) -> str:
    """
    建構 User prompt：問題 + 序列化後的 contexts。

    question: 投注問題，如 "Should I bet X over/under Y points?"
    contexts: 該 player+metric 下所有 filter 的 context 陣列
    """
    contexts_json = json.dumps(contexts, ensure_ascii=False, indent=2)
    return f"{question}\n\nContexts (apply different filters):\n{contexts_json}"


def call_openai(
    client,
    question: str,
    contexts: list[dict],
    model: str,
    temperature: float = 0.3,
) -> str | None:
    """
    呼叫 OpenAI Chat Completions API，取得結構化 JSON 答案。

    client: OpenAI 客戶端
    question: 投注問題
    contexts: contexts 陣列（依第八點建議使用 contexts 非 context）
    model: 模型名稱，如 gpt-4o-mini
    temperature: 較低值使輸出更穩定

    Returns:
        模型回傳的 content 字串，若失敗則回傳 None
    """
    user_content = build_user_prompt(question, contexts)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error("OpenAI API error: %s", e)
        return None


def validate_output(raw: str) -> tuple[bool, str]:
    """
    驗證模型輸出是否為合法 JSON 且符合品質要求。

    品質過濾（依 plan Phase 3.4）：
    - 必須為合法 JSON
    - decision 不可缺失
    - reasoning.tree_of_thought 不可過短（至少 1 步）

    Returns:
        (is_valid, error_message)
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"

    if "decision" not in data:
        return False, "Missing 'decision' field"

    decision = data.get("decision", "").lower()
    if decision not in ("over", "under", "avoid"):
        return False, f"Invalid decision: {decision}"

    reasoning = data.get("reasoning", {})
    tree = reasoning.get("tree_of_thought", [])
    if not isinstance(tree, list) or len(tree) < 1:
        return False, "reasoning.tree_of_thought too short or missing"

    return True, ""


def process_questions(
    input_path: Path,
    output_path: Path,
    model: str,
    limit: int | None,
    rate_limit_delay: float,
    max_retries: int,
) -> tuple[int, int]:
    """
    批次處理所有問題，呼叫 OpenAI 並寫入 train_full.jsonl。

    Returns:
        (成功筆數, 過濾掉筆數)
    """
    # 動態 import，避免未安裝 openai 時腳本無法載入
    try:
        from openai import OpenAI
    except ImportError:
        print("❌ 請安裝 openai: pip install openai")
        sys.exit(1)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("❌ 請設定環境變數 OPENAI_API_KEY")
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    # 讀取 train_questions.jsonl，使用 contexts 陣列（第八點建議）
    questions: list[dict] = []
    with open(input_path, "r", encoding="utf-8") as fin:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                # 確認使用 contexts（非 context）
                if "contexts" not in record:
                    logging.warning("Record missing 'contexts', skipping: %s", record.get("question", "")[:50])
                    continue
                questions.append(record)
            except json.JSONDecodeError as e:
                logging.warning("Invalid JSON line: %s", e)
                continue

    if limit is not None:
        questions = questions[:limit]
        logging.info("Limited to first %d questions", limit)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    success_count = 0
    filtered_count = 0

    with open(output_path, "w", encoding="utf-8") as fout:
        for i, record in enumerate(questions):
            question = record.get("question", "")
            contexts = record.get("contexts", [])

            if not contexts:
                logging.warning("Empty contexts for question %d, skipping", i + 1)
                filtered_count += 1
                continue

            # 重試邏輯
            raw_output = None
            for attempt in range(max_retries):
                raw_output = call_openai(client, question, contexts, model)
                if raw_output is not None:
                    break
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logging.info("Retry %d/%d after %ds...", attempt + 1, max_retries, wait)
                    time.sleep(wait)

            if raw_output is None:
                logging.error("Failed to get response for question %d", i + 1)
                filtered_count += 1
                continue

            # 品質過濾
            is_valid, err = validate_output(raw_output)
            if not is_valid:
                logging.warning("Filtered question %d: %s", i + 1, err)
                filtered_count += 1
                continue

            # 產出 Alpaca 格式：instruction, input, output
            alpaca_record = {
                "instruction": question,
                "input": json.dumps(contexts, ensure_ascii=False),
                "output": raw_output,
            }
            fout.write(json.dumps(alpaca_record, ensure_ascii=False) + "\n")
            success_count += 1

            # Rate limit
            if rate_limit_delay > 0:
                time.sleep(rate_limit_delay)

            if (i + 1) % 10 == 0:
                logging.info("Progress: %d/%d", i + 1, len(questions))

    return success_count, filtered_count


def main():
    parser = argparse.ArgumentParser(
        description="Phase 3: 使用 OpenAI 生成 Tree-of-Thought 結構化答案"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Phase 2 產出的 questions JSONL 路徑",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="輸出 train_full.jsonl 路徑",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o-mini",
        help="OpenAI 模型名稱（gpt-4o-mini, gpt-4o-mini 等）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="限制處理筆數（用於測試）",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=1.0,
        help="每次 API 呼叫間隔秒數",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="API 失敗時重試次數",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="顯示詳細 log",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if not args.input.exists():
        print(f"❌ 輸入檔案不存在: {args.input}")
        print("   請先執行 Phase 2: python scripts/dataset/02_generate_questions.py")
        sys.exit(1)

    print(f"📥 讀取 {args.input}")
    print(f"📤 輸出 {args.output}")
    print(f"🤖 模型 {args.model}")

    success, filtered = process_questions(
        args.input,
        args.output,
        args.model,
        args.limit,
        args.rate_limit,
        args.max_retries,
    )

    print(f"✅ 完成！成功 {success} 筆，過濾 {filtered} 筆，輸出至 {args.output}")


if __name__ == "__main__":
    main()
