#!/usr/bin/env python3
"""
01_sample_contexts.py - Phase 1: Context 樣本採集

從 CSV 採樣球員與情境，呼叫 csv_player_service.get_player_stats()，
產出結構化 context JSON 至 data/train_contexts.jsonl。

使用方式：
    # 從專案根目錄執行
    python scripts/dataset/01_sample_contexts.py

    # 或指定參數
    python scripts/dataset/01_sample_contexts.py --n-players 300 --n-contexts 800 --output data/train_contexts.jsonl
"""

import argparse
import json
import random
import sys
from pathlib import Path

# 將 backend 加入 Python path，才能 import app.services
project_root = Path(__file__).resolve().parent.parent.parent
backend_path = project_root / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app.services.csv_player_history import csv_player_service

# 預設路徑
DEFAULT_STAR_PLAYERS_PATH = project_root / "data" / "star_players.json"
DEFAULT_OUTPUT_PATH = project_root / "data" / "train_contexts.jsonl"

# 指標與對應的 display 名稱
METRICS = ["points", "assists", "rebounds", "pra"]

# 情境類型定義
# 每個 tuple: (n, opponent, is_starter, teammate_filter, teammate_played)
# n=0 表示全部場次；opponent=None 表示不篩選對手
# is_starter=None 表示不篩選先發/替補
# teammate_filter=None 表示不篩選星級隊友
Scenario = tuple  # (n: int, opponent: str|None, is_starter: bool|None, teammate_filter: list|None, teammate_played: bool|None)


def load_star_players(path: Path) -> dict[str, list[str]]:
    """讀取 star_players.json，回傳 Team -> [star names] 對照表"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_player_teams(player_name: str) -> list[str]:
    """
    取得球員曾效力的所有球隊（含季中交易）。
    用於星級隊友情境：需依每支效力過的球隊分別產生 with/without 星級隊友的情境。
    """
    stats = csv_player_service.get_player_stats(
        player_name, "points", 0, n=0
    )
    if stats.get("n_games", 0) == 0:
        return []
    game_logs = stats.get("game_logs", [])
    teams: set[str] = set()
    for g in game_logs:
        team = g.get("team", "")
        if team:
            teams.add(team)
    return sorted(teams)


def sample_threshold(mean: float, std: float, metric: str) -> float:
    """
    依 mean 附近隨機產生 threshold。
    使用 0.5 為步長，讓 threshold 為常見盤口格式（如 10.5, 24.5）。
    """
    if std <= 0:
        std = 1.0
    # 在 mean ± 1.5*std 範圍內隨機
    low = max(0, mean - 1.5 * std)
    high = mean + 1.5 * std
    if metric == "pra":
        high = max(high, 20)  # PRA 通常較大
    raw = random.uniform(low, high)
    # 取到 0.5
    return round(raw * 2) / 2


def build_scenarios(
    star_players: dict[str, list[str]],
    player_name: str,
    player_teams: list[str],
    opponents: list[str],
) -> list[Scenario]:
    """
    為單一球員建立多種情境。
    回傳 Scenario 列表。
    星級隊友情境：依球員曾效力的每支球隊、該隊的每位星級球員，分別產生 with/without 情境。
    """
    scenarios: list[Scenario] = []

    # 1. 全部場次
    scenarios.append((0, None, None, None, None))

    # 2. 最近 10 場
    scenarios.append((10, None, None, None, None))

    # 3. 最近 20 場
    scenarios.append((20, None, None, None, None))

    # 4. 對特定對手（隨機選一個，需有足夠樣本）
    if opponents:
        opp = random.choice(opponents)
        scenarios.append((0, opp, None, None, None))

    # 5. 僅先發
    scenarios.append((0, None, True, None, None))

    # 6. 僅替補
    scenarios.append((0, None, False, None, None))

    # 7. With 星級隊友 / 8. Without 星級隊友
    # 依球員曾效力的每支球隊、該隊的每位星級球員，分別產生情境（季中交易時可能效力多隊）
    # 排除球員自己（若自己被列為星級則跳過，避免「with 自己」的無意義情境）
    for team in player_teams:
        if team not in star_players:
            continue
        star_list = star_players[team]
        for star in star_list:
            if star == player_name:
                continue
            star_filter = [star]
            scenarios.append((0, None, None, star_filter, True))
            scenarios.append((0, None, None, star_filter, False))

    return scenarios


def _get_team_for_context(
    scenario: Scenario,
    stats: dict,
    star_players: dict[str, list[str]],
) -> str:
    """取得 context 的 team 欄位：有 teammate_filter 時從 star_players 反查；否則從 stats 第一筆 game 取得（反映該情境的球隊）。"""
    _, _, _, teammate_filter, _ = scenario
    if teammate_filter:
        for team, stars in star_players.items():
            if teammate_filter[0] in stars:
                return team
        return ""
    game_logs = stats.get("game_logs", [])
    if game_logs:
        return game_logs[0].get("team", "")
    return ""


def build_context_record(
    player_name: str,
    metric: str,
    threshold: float,
    scenario: Scenario,
    stats: dict,
    star_players: dict[str, list[str]],
) -> dict | None:
    """
    將 get_player_stats 的結果轉為 plan 定義的 context 格式。
    若 n_games 過少（< 3）則回傳 None，跳過該筆。
    """
    n_games = stats.get("n_games", 0)
    if n_games < 3:
        return None

    n, opponent, is_starter, teammate_filter, teammate_played = scenario

    filter_desc: dict = {}
    if n > 0:
        filter_desc["n"] = n
    if opponent:
        filter_desc["opponent"] = opponent
    if is_starter is not None:
        filter_desc["is_starter"] = is_starter
    if teammate_filter and teammate_played is not None:
        filter_desc["teammate_filter"] = teammate_filter
        filter_desc["teammate_played"] = teammate_played
        filter_desc["source"] = "star_players.json"

    team = _get_team_for_context(scenario, stats, star_players)

    return {
        "player": player_name,
        "team": team,
        "metric": metric,
        "threshold": threshold,
        "filter": filter_desc,
        "stats": {
            "n_games": n_games,
            "p_over": stats.get("p_over"),
            "p_under": stats.get("p_under"),
            "mean": stats.get("mean"),
            "std": stats.get("std"),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Phase 1: 採樣 context 至 train_contexts.jsonl")
    parser.add_argument(
        "--n-players",
        type=int,
        default=250,
        help="隨機採樣的球員數量（預設 250）",
    )
    parser.add_argument(
        "--n-contexts",
        type=int,
        default=0,
        help="目標 context 數量（0 表示不限制，盡量產出）",
    )
    parser.add_argument(
        "--star-players",
        type=Path,
        default=DEFAULT_STAR_PLAYERS_PATH,
        help="star_players.json 路徑",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="輸出 JSONL 路徑",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="隨機種子",
    )
    args = parser.parse_args()

    random.seed(args.seed)

    # 載入 star_players
    if not args.star_players.exists():
        print(f"❌ star_players.json 不存在: {args.star_players}")
        sys.exit(1)
    star_players = load_star_players(args.star_players)
    print(f"✅ 已載入 star_players，共 {len(star_players)} 隊")

    # 載入 CSV 並取得球員名單
    csv_player_service.load_csv()
    all_players = csv_player_service.get_all_players()
    print(f"✅ 已載入 CSV，共 {len(all_players)} 位球員")

    # 隨機採樣球員
    n_sample = min(args.n_players, len(all_players))
    sampled_players = random.sample(all_players, n_sample)
    print(f"📌 隨機採樣 {n_sample} 位球員")

    context_count = 0
    skipped = 0

    with open(args.output, "w", encoding="utf-8") as out:
        for player_name in sampled_players:
            if args.n_contexts > 0 and context_count >= args.n_contexts:
                break

            player_teams = get_player_teams(player_name)
            opponents = csv_player_service.get_player_opponents(player_name)
            scenarios = build_scenarios(star_players, player_name, player_teams, opponents)

            for metric in METRICS:
                # 同一 player+metric 共用一個 threshold，以「全部場次」為基準
                prelim = csv_player_service.get_player_stats(
                    player_name, metric, 0, n=0, opponent=None,
                    is_starter=None, teammate_filter=None, teammate_played=None,
                )
                if prelim.get("n_games", 0) < 5 or prelim.get("mean") is None:
                    skipped += len(scenarios)
                    continue

                mean = prelim["mean"]
                std = prelim.get("std") or 1.0
                threshold = sample_threshold(mean, std, metric)

                for scenario in scenarios:
                    if args.n_contexts > 0 and context_count >= args.n_contexts:
                        break

                    n, opponent, is_starter, teammate_filter, teammate_played = scenario

                    stats = csv_player_service.get_player_stats(
                        player_name,
                        metric,
                        threshold,
                        n=n,
                        opponent=opponent,
                        is_starter=is_starter,
                        teammate_filter=teammate_filter,
                        teammate_played=teammate_played,
                    )

                    record = build_context_record(
                        player_name, metric, threshold, scenario, stats, star_players
                    )
                    if record:
                        out.write(json.dumps(record, ensure_ascii=False) + "\n")
                        context_count += 1
                    else:
                        skipped += 1

    print(f"✅ 完成！產出 {context_count} 筆 context 至 {args.output}")
    print(f"   跳過 {skipped} 筆（樣本不足）")


if __name__ == "__main__":
    main()
