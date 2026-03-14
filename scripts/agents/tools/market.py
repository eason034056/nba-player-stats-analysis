"""
market.py – Dimension 7 pricing tools.

Data source: The Odds API (live) + PostgreSQL odds_line_snapshots (historical).

These tools are the pricing layer: they convert raw bookmaker odds into
fair probability, consensus, movement, best price, and bookmaker disagreement.

Because The Odds API calls are async and the LangGraph agent loop is sync,
each public function uses asyncio.run() to bridge the gap.
If the API key is missing or the request fails, the tool degrades gracefully.
"""

import asyncio
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

_AGENTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROJECT_ROOT = os.path.abspath(os.path.join(_AGENTS_DIR, "..", ".."))
_BACKEND_DIR = os.path.join(_PROJECT_ROOT, "backend")
if _AGENTS_DIR not in sys.path:
    sys.path.insert(0, _AGENTS_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from date_utils import normalize_date, date_to_utc_range
from app.services.normalize import canonical_name, extract_player_names, find_player, suggest_players
from app.services.prob import american_to_prob, devig, calculate_vig

_NOW_ISO = lambda: datetime.now(timezone.utc).isoformat()

MARKET_MAP = {
    "points": "player_points",
    "rebounds": "player_rebounds",
    "assists": "player_assists",
    "pra": "player_points_rebounds_assists",
}


def _signal_payload(signal, effect_size, sample_size, reliability, window, source, details):
    return {
        "signal": signal,
        "effect_size": round(effect_size, 4),
        "sample_size": sample_size,
        "reliability": round(min(max(reliability, 0.0), 1.0), 3),
        "window": window,
        "source": source,
        "as_of": _NOW_ISO(),
        "details": details,
    }


def _normalize_direction(direction: str, lines: List[Dict[str, Any]]) -> str:
    """Resolve 'any' into a concrete side using the current market."""
    dir_lower = (direction or "over").lower()
    if dir_lower != "any":
        return dir_lower
    fair_overs = [l["fair_over"] for l in lines]
    consensus_fair = statistics.mean(fair_overs) if fair_overs else 0.5
    return "over" if consensus_fair >= 0.5 else "under"


def _same_line_lines(lines: List[Dict[str, Any]], threshold: float) -> List[Dict[str, Any]]:
    return [l for l in lines if abs(l["line"] - float(threshold)) < 1e-9]


def _same_line_side_prob(lines: List[Dict[str, Any]], direction: str) -> Optional[float]:
    if not lines:
        return None
    fair_key = "fair_over" if direction == "over" else "fair_under"
    return statistics.mean([l[fair_key] for l in lines])


def _build_market_quote_for_line(
    lines: List[Dict[str, Any]],
    threshold: float,
    direction: str,
) -> Dict[str, Any]:
    available_lines = sorted({l["line"] for l in lines})
    dir_lower = _normalize_direction(direction, lines)

    if not threshold or threshold <= 0:
        return {
            "signal": "unavailable",
            "effect_size": 0,
            "sample_size": 0,
            "reliability": 0,
            "window": "today",
            "source": "odds_api",
            "as_of": _NOW_ISO(),
            "details": {
                "error": "queried line not specified",
                "pricing_mode": "overview_only",
                "direction": dir_lower,
                "queried_line": threshold,
                "available_lines": available_lines,
                "matched_n_books": 0,
            },
        }

    matched = _same_line_lines(lines, threshold)
    if not matched:
        return {
            "signal": "unavailable",
            "effect_size": 0,
            "sample_size": 0,
            "reliability": 0,
            "window": "today",
            "source": "odds_api",
            "as_of": _NOW_ISO(),
            "details": {
                "error": "queried line not currently available",
                "pricing_mode": "overview_only",
                "direction": dir_lower,
                "queried_line": threshold,
                "available_lines": available_lines,
                "matched_n_books": 0,
            },
        }

    key = "over_odds" if dir_lower == "over" else "under_odds"
    fair_key = "fair_over" if dir_lower == "over" else "fair_under"
    best = max(matched, key=lambda l: l[key])
    query_prob = _same_line_side_prob(matched, dir_lower)
    reliability = min(len(matched) / 6, 1.0)

    return _signal_payload(
        "neutral",
        (query_prob or 0.5) - 0.5,
        len(matched),
        reliability,
        "today",
        "odds_api",
        {
            "pricing_mode": "exact_line",
            "direction": dir_lower,
            "queried_line": float(threshold),
            "available_lines": available_lines,
            "matched_n_books": len(matched),
            "books": matched,
            "market_implied_for_query": round(query_prob, 4) if query_prob is not None else None,
            "best_book": best["bookmaker"],
            "best_odds": best[key],
            "best_line": best["line"],
            "best_fair_prob": best[fair_key],
        },
    )


# ---------------------------------------------------------------------------
# Async helpers to call The Odds API
# ---------------------------------------------------------------------------

async def _get_events(date: str = ""):
    """
    Fetch NBA events. The Odds API 使用 UTC。

    - date 為空：查 now-6h ~ now+18h（UTC）
    - date 為 YYYY-MM-DD：視為本地日期，轉成 UTC 區間後查詢
    """
    from app.services.odds_theoddsapi import odds_provider
    now = datetime.now(timezone.utc)
    date_from = now - timedelta(hours=6)
    date_to = now + timedelta(hours=18)

    # 先正規化（支援 "tomorrow" 等，若從其他路徑傳入）
    norm = normalize_date(date) if date else ""
    if norm:
        utc_range = date_to_utc_range(norm)
        if utc_range:
            start_utc, end_utc = utc_range
            # 若目標日期在未來，擴展查詢範圍
            if end_utc > now:
                date_from = min(date_from, start_utc)
                date_to = max(date_to, end_utc)

    return await odds_provider.get_events(
        sport="basketball_nba",
        regions="us",
        date_from=date_from,
        date_to=date_to,
    )


async def _get_player_odds(event_id: str, market_key: str):
    from app.services.odds_gateway import odds_gateway
    try:
        snapshot = await odds_gateway.get_market_snapshot(
            sport="basketball_nba",
            event_id=event_id,
            regions="us",
            markets=market_key,
            odds_format="american",
            priority="background",
            record_hot_key=False,
        )
        return snapshot.data
    except Exception:
        return {}


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _find_event_for_player(events: list, player: str) -> Optional[str]:
    """Heuristic: return first event_id (we can't deterministically match player->event without more data)."""
    return events[0]["id"] if events else None


def _collect_player_candidates(odds_data: dict) -> List[str]:
    players = set()
    for bm in odds_data.get("bookmakers", []):
        for mkt in bm.get("markets", []):
            players.update(extract_player_names(mkt.get("outcomes", [])))
    return sorted(players)


def _extract_player_lines(
    odds_data: dict,
    player: str,
) -> Tuple[List[Dict[str, Any]], Optional[str], List[str], List[Tuple[str, int]]]:
    """Pull all bookmaker lines for the matched player from an odds response."""
    candidates = _collect_player_candidates(odds_data)
    matched_player = find_player(player, candidates)
    suggestions = suggest_players(player, candidates, limit=5, threshold=70)

    if not matched_player:
        return [], None, candidates, suggestions

    matched_core = canonical_name(matched_player)
    matched_names = {candidate for candidate in candidates if canonical_name(candidate) == matched_core}
    results = []
    for bm in odds_data.get("bookmakers", []):
        bm_key = bm.get("key", "")
        for mkt in bm.get("markets", []):
            outs_by_player: Dict[str, dict] = {}
            for o in mkt.get("outcomes", []):
                desc = o.get("description", "")
                if desc not in matched_names:
                    continue
                direction = o.get("name", "").lower()
                outs_by_player[direction] = o

            over_o = outs_by_player.get("over")
            under_o = outs_by_player.get("under")
            if over_o and under_o:
                line = over_o.get("point")
                over_price = over_o.get("price", 0)
                under_price = under_o.get("price", 0)
                if line is not None and over_price and under_price:
                    try:
                        p_over = american_to_prob(over_price)
                        p_under = american_to_prob(under_price)
                        vig = calculate_vig(p_over, p_under)
                        fair_over, fair_under = devig(p_over, p_under)
                        results.append({
                            "bookmaker": bm_key,
                            "line": float(line),
                            "over_odds": int(over_price),
                            "under_odds": int(under_price),
                            "vig": round(vig, 4),
                            "fair_over": round(fair_over, 4),
                            "fair_under": round(fair_under, 4),
                        })
                    except (ValueError, ZeroDivisionError):
                        continue
    return results, matched_player, candidates, suggestions


async def _fetch_market_data(player: str, metric: str, date: str = "") -> Tuple[List[Dict[str, Any]], Optional[str], Dict[str, Any]]:
    """Returns (lines, market_key, meta). meta contains match/error context for the caller."""
    market_key = MARKET_MAP.get(metric, f"player_{metric}")
    events = await _get_events(date)
    if not events:
        return [], None, {
            "error": "no NBA events in time window (try expanding date or check API)",
            "query_player_name": player,
            "searched_events": 0,
        }

    lines_all = []
    matched_player = None
    all_candidates = set()
    best_suggestions: List[Tuple[str, int]] = []
    for ev in events:
        odds = await _get_player_odds(ev["id"], market_key)
        lines, matched_name, candidates, suggestions = _extract_player_lines(odds, player)
        all_candidates.update(candidates)
        if suggestions and not best_suggestions:
            best_suggestions = suggestions
        if lines:
            lines_all = lines
            matched_player = matched_name
            break

    if lines_all:
        return lines_all, market_key, {
            "query_player_name": player,
            "matched_player_name": matched_player or player,
            "searched_events": len(events),
        }

    suggestions = suggest_players(player, sorted(all_candidates), limit=5, threshold=70) or best_suggestions
    return [], market_key, {
        "error": "player not found in any event",
        "hint": "check name spelling or try the sportsbook version, e.g. Cody Williams Jr.",
        "query_player_name": player,
        "suggestions": [{"name": name, "score": score} for name, score in suggestions],
        "candidate_count": len(all_candidates),
        "searched_events": len(events),
    }


# ===================================================================
# PUBLIC TOOLS
# ===================================================================

def get_current_market(player: str, metric: str, date: str = "") -> Dict[str, Any]:
    """All bookmaker lines, no-vig fair probability, consensus."""
    try:
        lines, mkt_key, meta = _run_async(_fetch_market_data(player, metric, date))
    except Exception as e:
        return _signal_payload("unavailable", 0, 0, 0, "today", "odds_api",
                               {"error": str(e)})

    if not lines:
        details = dict(meta)
        details.setdefault("error", "no lines found for player/metric")
        return _signal_payload("unavailable", 0, 0, 0, "today", "odds_api", details)

    fair_overs = [l["fair_over"] for l in lines]
    consensus_fair = statistics.mean(fair_overs)
    consensus_line = statistics.median([l["line"] for l in lines])

    sig = "over" if consensus_fair > 0.55 else ("under" if consensus_fair < 0.45 else "neutral")
    return _signal_payload(sig, consensus_fair - 0.5, len(lines), min(len(lines) / 6, 1.0), "today", "odds_api",
                           {"consensus_fair_over": round(consensus_fair, 4),
                            "consensus_line": consensus_line,
                            "books": lines,
                            "n_books": len(lines),
                            "query_player_name": meta.get("query_player_name", player),
                            "matched_player_name": meta.get("matched_player_name", player)})


def get_line_movement(player: str, metric: str, date: str = "") -> Dict[str, Any]:
    """Opening vs current line, direction, magnitude."""
    try:
        lines, _, meta = _run_async(_fetch_market_data(player, metric, date))
    except Exception as e:
        return _signal_payload("unavailable", 0, 0, 0, "today", "odds_api", {"error": str(e)})

    if not lines:
        details = dict(meta)
        details.setdefault("error", "no lines")
        return _signal_payload("unavailable", 0, 0, 0, "today", "odds_api", details)

    all_lines = [l["line"] for l in lines]
    current = statistics.median(all_lines)

    return _signal_payload("neutral", 0, len(lines), min(len(lines) / 6, 1.0), "today", "odds_api",
                           {"current_consensus_line": current,
                            "all_lines": sorted(set(all_lines)),
                            "note": "snapshot only; historical movement requires stored odds_line_snapshots",
                            "query_player_name": meta.get("query_player_name", player),
                            "matched_player_name": meta.get("matched_player_name", player)})


def get_best_price(player: str, metric: str, direction: str, date: str = "") -> Dict[str, Any]:
    """Best currently available line/odds for the intended side (over or under)."""
    try:
        lines, _, meta = _run_async(_fetch_market_data(player, metric, date))
    except Exception as e:
        return _signal_payload("unavailable", 0, 0, 0, "today", "odds_api", {"error": str(e)})

    if not lines:
        details = dict(meta)
        details.setdefault("error", "no lines")
        return _signal_payload("unavailable", 0, 0, 0, "today", "odds_api", details)

    dir_lower = _normalize_direction(direction, lines)

    key = "over_odds" if dir_lower == "over" else "under_odds"
    fair_key = "fair_over" if dir_lower == "over" else "fair_under"
    best = max(lines, key=lambda l: l[key])

    return _signal_payload("neutral", 0, len(lines), min(len(lines) / 6, 1.0), "today", "odds_api",
                           {"direction": dir_lower,
                            "best_book": best["bookmaker"],
                            "best_odds": best[key],
                            "best_line": best["line"],
                            "best_fair_prob": best[fair_key],
                            "query_player_name": meta.get("query_player_name", player),
                            "matched_player_name": meta.get("matched_player_name", player)})


def get_market_quote_for_line(
    player: str,
    metric: str,
    threshold: float,
    direction: str,
    date: str = "",
) -> Dict[str, Any]:
    """
    Query-specific market quote.

    Unlike get_current_market(), this only prices the exact line the user asked about.
    If the queried line is not currently available, it returns unavailable and includes
    the available market lines for debugging/UI display.
    """
    try:
        lines, _, meta = _run_async(_fetch_market_data(player, metric, date))
    except Exception as e:
        return _signal_payload(
            "unavailable",
            0,
            0,
            0,
            "today",
            "odds_api",
            {"error": str(e), "queried_line": threshold, "pricing_mode": "overview_only"},
        )

    if not lines:
        details = dict(meta)
        details.setdefault("error", "no lines")
        details.update({"queried_line": threshold, "pricing_mode": "overview_only"})
        return _signal_payload("unavailable", 0, 0, 0, "today", "odds_api", details)

    result = _build_market_quote_for_line(lines, threshold, direction)
    result["details"]["query_player_name"] = meta.get("query_player_name", player)
    result["details"]["matched_player_name"] = meta.get("matched_player_name", player)
    return result


def get_bookmaker_spread(player: str, metric: str, date: str = "") -> Dict[str, Any]:
    """Disagreement across books – wide spread = uncertain market."""
    try:
        lines, _, meta = _run_async(_fetch_market_data(player, metric, date))
    except Exception as e:
        return _signal_payload("unavailable", 0, 0, 0, "today", "odds_api", {"error": str(e)})

    if not lines:
        details = dict(meta)
        details.setdefault("error", "no lines")
        return _signal_payload("unavailable", 0, 0, 0, "today", "odds_api", details)

    all_lines = [l["line"] for l in lines]
    spread = max(all_lines) - min(all_lines)
    std = statistics.stdev(all_lines) if len(all_lines) > 1 else 0

    sig = "caution" if spread > 2 else "neutral"
    return _signal_payload(sig, spread, len(lines), min(len(lines) / 6, 1.0), "today", "odds_api",
                           {"line_spread": spread,
                            "line_std": round(std, 2),
                            "min_line": min(all_lines),
                            "max_line": max(all_lines),
                            "interpretation": "wide disagreement" if spread > 2 else "tight consensus",
                            "query_player_name": meta.get("query_player_name", player),
                            "matched_player_name": meta.get("matched_player_name", player)})


ALL_MARKET_TOOLS = [
    get_current_market,
    get_line_movement,
    get_best_price,
    get_market_quote_for_line,
    get_bookmaker_spread,
]
