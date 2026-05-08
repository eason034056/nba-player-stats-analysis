#!/usr/bin/env python3
"""
04_merge_and_split.py - Phase 4: 資料集格式與切分

讀取 Phase 3 產出的 train_full.jsonl，打亂順序後切分為：
- train 80%：訓練集
- eval 10%：驗證集（訓練時監控）
- test 10%：測試集（不參與訓練，用於 base vs fine-tuned 比較）

輸出格式：Alpaca / HuggingFace datasets 相容（instruction, input, output）

使用方式：
    # 從專案根目錄執行
    python scripts/dataset/04_merge_and_split.py

    # 指定輸入/輸出、切分比例、seed
    python scripts/dataset/04_merge_and_split.py --input data/train_full.jsonl --seed 42
"""

import argparse
import json
import random
import sys
from pathlib import Path

# 專案根目錄
project_root = Path(__file__).resolve().parent.parent.parent

DEFAULT_INPUT_PATH = project_root / "data" / "train_full.jsonl"
DEFAULT_OUTPUT_DIR = project_root / "data"


def load_records(input_path: Path) -> list[dict]:
    """讀取 JSONL，每行一筆 Alpaca 格式記錄。"""
    records = []
    with open(input_path, "r", encoding="utf-8") as fin:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def shuffle_and_split(
    records: list[dict],
    train_ratio: float,
    eval_ratio: float,
    test_ratio: float,
    seed: int,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    打亂順序後依比例切分。

    train_ratio + eval_ratio + test_ratio 應為 1.0
    """
    rng = random.Random(seed)
    shuffled = records.copy()
    rng.shuffle(shuffled)

    n = len(shuffled)
    n_train = int(n * train_ratio)
    n_eval = int(n * eval_ratio)
    n_test = n - n_train - n_eval

    train_data = shuffled[:n_train]
    eval_data = shuffled[n_train : n_train + n_eval]
    test_data = shuffled[n_train + n_eval :]

    return train_data, eval_data, test_data


def write_jsonl(path: Path, records: list[dict]) -> None:
    """寫入 JSONL 檔案。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fout:
        for r in records:
            fout.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Phase 4: 合併、打亂、切分 train/eval/test"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Phase 3 產出的 train_full.jsonl 路徑",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="輸出目錄",
    )
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.8,
        help="訓練集比例",
    )
    parser.add_argument(
        "--eval-ratio",
        type=float,
        default=0.1,
        help="驗證集比例",
    )
    parser.add_argument(
        "--test-ratio",
        type=float,
        default=0.1,
        help="測試集比例",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="隨機種子（可重現打亂）",
    )
    args = parser.parse_args()

    total = args.train_ratio + args.eval_ratio + args.test_ratio
    if abs(total - 1.0) > 1e-6:
        print(f"❌ 比例總和應為 1.0，目前為 {total}")
        sys.exit(1)

    if not args.input.exists():
        print(f"❌ 輸入檔案不存在: {args.input}")
        print("   請先執行 Phase 3: python scripts/dataset/03_generate_answers.py")
        sys.exit(1)

    records = load_records(args.input)
    if not records:
        print("❌ 無有效記錄")
        sys.exit(1)

    train_data, eval_data, test_data = shuffle_and_split(
        records,
        args.train_ratio,
        args.eval_ratio,
        args.test_ratio,
        args.seed,
    )

    out = args.output_dir
    write_jsonl(out / "train.jsonl", train_data)
    write_jsonl(out / "eval.jsonl", eval_data)
    write_jsonl(out / "test.jsonl", test_data)

    print(f"📥 讀取 {len(records)} 筆（已打亂，seed={args.seed}）")
    print(f"📤 輸出至 {out}")
    print(f"   train.jsonl: {len(train_data)} 筆 ({args.train_ratio*100:.0f}%)")
    print(f"   eval.jsonl:  {len(eval_data)} 筆 ({args.eval_ratio*100:.0f}%)")
    print(f"   test.jsonl:  {len(test_data)} 筆 ({args.test_ratio*100:.0f}%)")
    print("✅ 完成！")


if __name__ == "__main__":
    main()
