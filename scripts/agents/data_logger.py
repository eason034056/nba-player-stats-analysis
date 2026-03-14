"""
data_logger.py – 將 Agent 抓取的所有資料以可讀格式輸出，並附上中文解釋。

用途：除錯、了解 Agent 決策依據、驗證資料來源。
使用方式：在 cli.py 加上 --log-data 參數，或直接呼叫 log_all_agent_data(state)。
"""

import json
from typing import Any, Dict


# 每個 tool 的中文解釋（對應 agents.py 中實際呼叫的 tools）
TOOL_EXPLANATIONS = {
    # ========== Historical Agent (Dimension 1-5) ==========
    "get_base_stats": {
        "name": "基礎統計 (Base Stats)",
        "desc": "從 CSV 歷史資料計算該球員在指定指標（如 points）的整體表現：平均、中位數、標準差、過線率。⚠️ hit_rate/shrunk_rate 永遠是 P(over > threshold)，Under 查詢需用 1 - hit_rate。",
        "source": "nba_player_game_logs.csv",
        "fields": ["mean", "median", "hit_rate", "over_count", "total"],
    },
    "get_starter_bench_split": {
        "name": "先發/替補分拆 (Starter vs Bench)",
        "desc": "比較球員擔任先發 vs 替補時的表現差異。先發平均較高可能偏向 over。⚠️ hit_rate 永遠是 P(over)。",
        "source": "csv (is_starter 欄位)",
        "fields": ["starter", "bench"],
    },
    "get_opponent_history": {
        "name": "對戰對手歷史 (vs Opponent)",
        "desc": "該球員過去對戰此對手的表現。若有對手資訊才會執行。⚠️ hit_rate 永遠是 P(over)。",
        "source": "csv (opponent 欄位)",
        "fields": ["hit_rate", "mean", "games"],
    },
    "get_trend_analysis": {
        "name": "趨勢分析 (Trend Analysis)",
        "desc": "比較近 3/5/10/20 場與整季平均，判斷近期是否升溫或降溫。",
        "source": "csv",
        "fields": ["rolling_averages", "season_avg", "recent_vs_season_pct"],
    },
    "get_streak_info": {
        "name": "連勝/連敗 (Streak Info)",
        "desc": "目前連續 over/under 的場數，以及史上最長連 over/under。",
        "source": "csv",
        "fields": ["current_streak", "longest_over_streak", "longest_under_streak"],
    },
    "get_minutes_role_trend": {
        "name": "上場時間趨勢 (Minutes Role Trend)",
        "desc": "近 5 場 vs 整季平均上場時間，以及近 10 場先發比例。",
        "source": "csv",
        "fields": ["season_avg_min", "last5_avg_min", "starter_pct_last10"],
    },
    "get_shooting_profile": {
        "name": "投籃效率 (Shooting Profile)",
        "desc": "FG%/3P%/FT% 整季 vs 近 5 場，判斷是否過熱（回歸風險）或過冷（反彈機會）。",
        "source": "csv",
        "fields": ["season", "last_5", "fg_diff", "flags"],
    },
    "get_variance_profile": {
        "name": "變異性/穩定性 (Variance Profile)",
        "desc": "變異係數 (CV)、P10/P50/P90 分位數。CV 高表示表現起伏大，較難預測。",
        "source": "csv",
        "fields": ["mean", "std", "cv", "p10", "p50", "p90"],
    },
    "get_schedule_context": {
        "name": "賽程情境 (Schedule Context)",
        "desc": "距離上一場休息天數、是否背靠背 (B2B)、不同休息天數下的平均上場時間。",
        "source": "csv (game_date)",
        "fields": ["days_rest", "is_back_to_back", "avg_minutes_by_rest"],
    },
    "get_game_script_splits": {
        "name": "勝負分拆 (Win/Loss Splits)",
        "desc": "贏球 vs 輸球時的表現差異。垃圾時間可能影響輸球場次的數據。⚠️ hit_rate 永遠是 P(over)。",
        "source": "csv (wl 欄位)",
        "fields": ["wins", "losses", "diff"],
    },
    "auto_teammate_impact": {
        "name": "隊友影響 (Teammate Impact)",
        "desc": "明星隊友在/不在場時，該球員的表現差異。結合傷兵報告判斷今日情境。",
        "source": "csv + star_players.json + ESPN/CBS 傷兵報告",
        "fields": ["teammate_chemistry", "today_scenario"],
    },
    "get_official_injury_report": {
        "name": "官方傷兵報告 (Injury Report)",
        "desc": "對手球隊的傷兵名單（ESPN + CBS 爬取）。影響對手防守強度與輪替。",
        "source": "nba_lineup_rag (ESPN/CBS injury pages)",
        "fields": ["team", "injuries"],
    },
    # ========== Market Agent (Dimension 7) ==========
    "get_current_market": {
        "name": "當前盤口 (Current Market)",
        "desc": "從 The Odds API 取得各家博彩商的賠率，計算 consensus line、去 vig 後的公平機率。⚠️ consensus_fair_over 永遠是 P(over)。Under 查詢需用 1 - consensus_fair_over。",
        "source": "The Odds API (live)",
        "fields": ["consensus_fair_over", "consensus_line", "books", "n_books"],
    },
    "get_line_movement": {
        "name": "盤口變動 (Line Movement)",
        "desc": "開盤 vs 當前 consensus line。若需歷史變動需查 odds_line_snapshots。",
        "source": "The Odds API",
        "fields": ["current_consensus_line", "all_lines"],
    },
    "get_best_price": {
        "name": "最佳賠率 (Best Price)",
        "desc": "over/under 方向的最佳賠率與對應博彩商。",
        "source": "The Odds API",
        "fields": ["direction", "best_book", "best_odds", "best_line"],
    },
    "get_market_quote_for_line": {
        "name": "同線報價 (Same-Line Quote)",
        "desc": "只針對使用者查詢的 threshold 計算市場機率與最佳報價。若查詢是 under 24.5，就只使用 24.5 這條線；不會把 23.5/24.5 混在一起算 EV。",
        "source": "The Odds API",
        "fields": ["pricing_mode", "queried_line", "available_lines", "matched_n_books", "market_implied_for_query", "best_book", "best_odds", "best_line"],
    },
    "get_bookmaker_spread": {
        "name": "博彩商分歧 (Bookmaker Spread)",
        "desc": "各家 line 的差異（min/max/std）。分歧大表示市場不確定。",
        "source": "The Odds API",
        "fields": ["line_spread", "min_line", "max_line", "interpretation"],
    },
    # ========== Projection Agent (Dimension 6 - stub) ==========
    "get_full_projection": {
        "name": "完整投影 (Full Projection)",
        "desc": "預測點數/籃板/助攻/PRA、上場時間、usage%。目前為 stub，SportsDataIO 為假資料。",
        "source": "unavailable (SportsDataIO dummy)",
        "fields": [],
    },
    "calculate_edge": {
        "name": "邊際優勢 (Edge)",
        "desc": "預測值減去門檻。目前為 stub。",
        "source": "unavailable",
        "fields": [],
    },
    "get_opponent_defense_profile": {
        "name": "對手防守檔位 (Opponent Defense)",
        "desc": "對手防守排名、位置對位排名。目前為 stub。",
        "source": "unavailable",
        "fields": [],
    },
    "get_minutes_confidence": {
        "name": "上場時間信心 (Minutes Confidence)",
        "desc": "投影上場時間 vs CSV 整季平均。目前為 stub。",
        "source": "unavailable",
        "fields": [],
    },
}


def _format_signal(s: Dict[str, Any], indent: str = "    ") -> str:
    """將單一 signal 格式化為可讀字串。"""
    lines = []
    lines.append(f"{indent}signal: {s.get('signal', '?')}")
    lines.append(f"{indent}effect_size: {s.get('effect_size', 0)}")
    lines.append(f"{indent}sample_size: {s.get('sample_size', 0)}")
    lines.append(f"{indent}reliability: {s.get('reliability', 0)}")
    lines.append(f"{indent}window: {s.get('window', '?')}")
    lines.append(f"{indent}source: {s.get('source', '?')}")
    lines.append(f"{indent}as_of: {s.get('as_of', '?')}")
    details = s.get("details")
    if details:
        lines.append(f"{indent}details: {json.dumps(details, indent=2, default=str)}")
    return "\n".join(lines)


def _log_signal_group(
    signals: Dict[str, Any],
    group_name: str,
    explanations: Dict[str, dict],
) -> str:
    """輸出單一 signal 群組（historical / market / projection）的完整內容。"""
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"  【{group_name}】")
    lines.append(f"{'='*60}")

    for tool_name, data in signals.items():
        if not isinstance(data, dict):
            continue

        exp = explanations.get(tool_name, {})
        name = exp.get("name", tool_name)
        desc = exp.get("desc", "")
        source = exp.get("source", "unknown")

        lines.append(f"\n  ▶ {name}")
        lines.append(f"    說明: {desc}")
        lines.append(f"    資料來源: {source}")
        lines.append("")
        lines.append(_format_signal(data))

    return "\n".join(lines)


def log_all_agent_data(state: Dict[str, Any]) -> None:
    """
    將 Agent 抓取的所有資料輸出到 stdout，並附上中文解釋。

    Args:
        state: 完整 graph 執行後的 final_state（包含 parsed_query, historical_signals,
               market_signals, projection_signals 等）
    """
    print("\n" + "━" * 64)
    print("  📊 AGENT 抓取資料總覽 (含解釋)")
    print("━" * 64)

    # 1. Parsed Query
    pq = state.get("parsed_query", {})
    if pq:
        print("\n【Planner 解析結果】")
        print(f"   球員: {pq.get('player', '?')}")
        print(f"   指標: {pq.get('metric', '?')}")
        print(f"   門檻: {pq.get('threshold', '?')}")
        print(f"   日期: {pq.get('date', '?')}")
        print(f"   對手: {pq.get('opponent', '?')}")
        print(f"   方向: {pq.get('direction', '?')}")

    # 2. Historical Signals
    hist = state.get("historical_signals", {})
    if hist:
        print(_log_signal_group(hist, "Historical Agent (維度 1–5)", TOOL_EXPLANATIONS))

    # 3. Market Signals
    market = state.get("market_signals", {})
    if market:
        print(_log_signal_group(market, "Market Agent (維度 7)", TOOL_EXPLANATIONS))
        same_line = (market.get("get_market_quote_for_line", {}) or {}).get("details", {})
        if same_line:
            print("  [Market Note]")
            print("    - get_current_market 是市場總覽，可能同時列出多條 line。")
            print("    - get_market_quote_for_line 才是拿來計算 scorecard EV 的同線報價。")
            if same_line.get("pricing_mode") != "exact_line":
                available = same_line.get("available_lines") or []
                if available:
                    print(f"    - 查詢線沒有精準對上，目前可用線: {', '.join(str(line) for line in available)}")
                print("    - 因為沒有 exact queried line，系統不會用 mixed lines 計算 EV。")

    # 4. Projection Signals
    proj = state.get("projection_signals", {})
    if proj:
        print(_log_signal_group(proj, "Projection Agent (維度 6 – stub)", TOOL_EXPLANATIONS))

    # 5. Data Quality Flags
    flags = state.get("data_quality_flags", [])
    if flags:
        print("\n" + "=" * 60)
        print("  【資料品質旗標】")
        print("=" * 60)
        for f in flags:
            print(f"    - {f}")

    print("\n" + "━" * 64 + "\n")
