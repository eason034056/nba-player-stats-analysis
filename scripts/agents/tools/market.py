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
import statistics
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_BACKEND_DIR = os.path.join(_PROJECT_ROOT, "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

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


# ---------------------------------------------------------------------------
# Async helpers to call The Odds API
# ---------------------------------------------------------------------------

async def _get_events_today():
    from app.services.odds_theoddsapi import odds_provider
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    return await odds_provider.get_events(
        sport="basketball_nba",
        regions="us",
        date_from=now - timedelta(hours=6),
        date_to=now + timedelta(hours=18),
    )


async def _get_player_odds(event_id: str, market_key: str):
    from app.services.odds_theoddsapi import odds_provider
    try:
        return await odds_provider.get_event_odds(
            sport="basketball_nba",
            event_id=event_id,
            regions="us",
            markets=market_key,
            odds_format="american",
        )
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


def _extract_player_lines(odds_data: dict, player: str) -> List[Dict[str, Any]]:
    """Pull all bookmaker lines for a given player from an odds response."""
    player_low = player.lower()
    results = []
    for bm in odds_data.get("bookmakers", []):
        bm_key = bm.get("key", "")
        for mkt in bm.get("markets", []):
            outs_by_player: Dict[str, dict] = {}
            for o in mkt.get("outcomes", []):
                desc = o.get("description", "")
                if desc.lower() != player_low:
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
    return results


async def _fetch_market_data(player: str, metric: str):
    market_key = MARKET_MAP.get(metric, f"player_{metric}")
    events = await _get_events_today()
    if not events:
        return [], None

    lines_all = []
    for ev in events:
        odds = await _get_player_odds(ev["id"], market_key)
        lines = _extract_player_lines(odds, player)
        if lines:
            lines_all = lines
            break

    return lines_all, market_key


# ===================================================================
# PUBLIC TOOLS
# ===================================================================

def get_current_market(player: str, metric: str, date: str = "") -> Dict[str, Any]:
    """All bookmaker lines, no-vig fair probability, consensus."""
    try:
        lines, mkt_key = _run_async(_fetch_market_data(player, metric))
    except Exception as e:
        return _signal_payload("unavailable", 0, 0, 0, "today", "odds_api",
                               {"error": str(e)})

    if not lines:
        return _signal_payload("unavailable", 0, 0, 0, "today", "odds_api",
                               {"error": "no lines found for player/metric"})

    fair_overs = [l["fair_over"] for l in lines]
    consensus_fair = statistics.mean(fair_overs)
    consensus_line = statistics.median([l["line"] for l in lines])

    sig = "over" if consensus_fair > 0.55 else ("under" if consensus_fair < 0.45 else "neutral")
    return _signal_payload(sig, consensus_fair - 0.5, len(lines), min(len(lines) / 6, 1.0), "today", "odds_api",
                           {"consensus_fair_over": round(consensus_fair, 4),
                            "consensus_line": consensus_line,
                            "books": lines,
                            "n_books": len(lines)})


def get_line_movement(player: str, metric: str, date: str = "") -> Dict[str, Any]:
    """Opening vs current line, direction, magnitude."""
    try:
        lines, _ = _run_async(_fetch_market_data(player, metric))
    except Exception as e:
        return _signal_payload("unavailable", 0, 0, 0, "today", "odds_api", {"error": str(e)})

    if not lines:
        return _signal_payload("unavailable", 0, 0, 0, "today", "odds_api", {"error": "no lines"})

    all_lines = [l["line"] for l in lines]
    current = statistics.median(all_lines)

    return _signal_payload("neutral", 0, len(lines), min(len(lines) / 6, 1.0), "today", "odds_api",
                           {"current_consensus_line": current,
                            "all_lines": sorted(set(all_lines)),
                            "note": "snapshot only; historical movement requires stored odds_line_snapshots"})


def get_best_price(player: str, metric: str, direction: str, date: str = "") -> Dict[str, Any]:
    """Best currently available line/odds for the intended side (over or under)."""
    try:
        lines, _ = _run_async(_fetch_market_data(player, metric))
    except Exception as e:
        return _signal_payload("unavailable", 0, 0, 0, "today", "odds_api", {"error": str(e)})

    if not lines:
        return _signal_payload("unavailable", 0, 0, 0, "today", "odds_api", {"error": "no lines"})

    key = "over_odds" if direction.lower() == "over" else "under_odds"
    best = max(lines, key=lambda l: l[key])

    return _signal_payload("neutral", 0, len(lines), min(len(lines) / 6, 1.0), "today", "odds_api",
                           {"direction": direction,
                            "best_book": best["bookmaker"],
                            "best_odds": best[key],
                            "best_line": best["line"],
                            "best_fair_prob": best["fair_over"] if direction.lower() == "over" else best["fair_under"]})


def get_bookmaker_spread(player: str, metric: str, date: str = "") -> Dict[str, Any]:
    """Disagreement across books – wide spread = uncertain market."""
    try:
        lines, _ = _run_async(_fetch_market_data(player, metric))
    except Exception as e:
        return _signal_payload("unavailable", 0, 0, 0, "today", "odds_api", {"error": str(e)})

    if not lines:
        return _signal_payload("unavailable", 0, 0, 0, "today", "odds_api", {"error": "no lines"})

    all_lines = [l["line"] for l in lines]
    spread = max(all_lines) - min(all_lines)
    std = statistics.stdev(all_lines) if len(all_lines) > 1 else 0

    sig = "caution" if spread > 2 else "neutral"
    return _signal_payload(sig, spread, len(lines), min(len(lines) / 6, 1.0), "today", "odds_api",
                           {"line_spread": spread,
                            "line_std": round(std, 2),
                            "min_line": min(all_lines),
                            "max_line": max(all_lines),
                            "interpretation": "wide disagreement" if spread > 2 else "tight consensus"})


ALL_MARKET_TOOLS = [
    get_current_market,
    get_line_movement,
    get_best_price,
    get_bookmaker_spread,
]
