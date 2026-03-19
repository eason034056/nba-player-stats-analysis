"""
historical.py – Structured tools for Dimensions 1-5.

Data sources used (Phase 1 stack):
  - Existing CSV  (nba_player_game_logs.csv via csv_player_service)
  - Official Injury Report (ESPN + CBS via nba_lineup_rag scraper)

Every public tool returns a dict conforming to the signal contract:
  { signal, effect_size, sample_size, reliability, window, source, as_of, details }
"""

import asyncio
import json
import math
import os
import statistics
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Path bootstrap – allow imports from both the backend and nba_lineup_rag
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_BACKEND_DIR = os.path.join(_PROJECT_ROOT, "backend")
_RAG_DIR = os.path.join(_PROJECT_ROOT, "nba_lineup_rag")

for _p in (_BACKEND_DIR, _RAG_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.services.csv_player_history import CSVPlayerHistoryService

_STAR_PLAYERS_PATH = os.path.join(_PROJECT_ROOT, "data", "star_players.json")

# ---------------------------------------------------------------------------
# Singleton CSV service shared by all tools
# ---------------------------------------------------------------------------
_csv_svc = CSVPlayerHistoryService()
_csv_svc.load_csv()

# ---------------------------------------------------------------------------
# Star-players registry
# ---------------------------------------------------------------------------
def _load_star_players() -> Dict[str, List[str]]:
    try:
        with open(_STAR_PLAYERS_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

_STAR_PLAYERS: Dict[str, List[str]] = _load_star_players()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_NOW_ISO = lambda: datetime.now(timezone.utc).isoformat()


def _signal_payload(
    signal: str,
    effect_size: float,
    sample_size: int,
    reliability: float,
    window: str,
    source: str,
    details: Dict[str, Any],
) -> Dict[str, Any]:
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


def _reliability_from_n(n: int, min_n: int = 10, full_n: int = 50) -> float:
    """Ramp reliability linearly from 0 at min_n to 1 at full_n."""
    if n < min_n:
        return 0.0
    return min((n - min_n) / max(full_n - min_n, 1), 1.0)


def _shrink(raw_rate: float, n: int, prior: float = 0.5, k: float = 15.0) -> float:
    """Bayesian shrinkage toward *prior*. k controls shrinkage strength."""
    return (raw_rate * n + prior * k) / (n + k)


def _games_for(player: str, n: int = 0) -> List[Dict[str, Any]]:
    """Return game logs, newest-first, optionally limited to last *n*."""
    _csv_svc.load_csv()
    logs = _csv_svc._cache.get(player, [])
    if not logs:
        low = player.lower()
        for p in _csv_svc._all_players:
            if low in p.lower() or p.lower() in low:
                logs = _csv_svc._cache.get(p, [])
                break
    active = [g for g in logs if g.get("minutes", 0) > 0]
    if n > 0:
        active = active[:n]
    return active


def _values(games: List[Dict], metric: str) -> List[float]:
    return [g[metric] for g in games if g.get(metric) is not None]


def _hit_rate(values: List[float], threshold: float) -> Tuple[float, int, int]:
    over = sum(1 for v in values if v > threshold)
    return (over / len(values) if values else 0.0, over, len(values))


def _direction(rate: float) -> str:
    if rate >= 0.58:
        return "over"
    if rate <= 0.42:
        return "under"
    return "neutral"


def _build_base_rate_signal(
    games: List[Dict[str, Any]],
    metric: str,
    threshold: float,
    *,
    window: str,
    source: str,
    reliability_min_n: int = 10,
    reliability_full_n: int = 50,
    extra_details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    vals = _values(games, metric)
    if not vals:
        return _signal_payload(
            "unavailable",
            0,
            0,
            0,
            window,
            source,
            {"error": f"no data for {metric}"},
        )

    rate, over, total = _hit_rate(vals, threshold)
    mean = statistics.mean(vals)
    med = statistics.median(vals)
    std = statistics.stdev(vals) if len(vals) > 1 else 0.0
    shrunk = _shrink(rate, total)
    rel = _reliability_from_n(total, min_n=reliability_min_n, full_n=reliability_full_n)

    details = {
        "hit_rate": round(rate, 4),
        "shrunk_rate": round(shrunk, 4),
        "mean": round(mean, 2),
        "median": round(med, 2),
        "std": round(std, 2),
        "over_count": over,
        "total": total,
    }
    if extra_details:
        details.update(extra_details)

    return _signal_payload(
        signal=_direction(shrunk),
        effect_size=mean - threshold,
        sample_size=total,
        reliability=rel,
        window=window,
        source=source,
        details=details,
    )


# ===================================================================
# DIMENSION 1 – Base Distribution / Role Splits
# ===================================================================

def get_base_stats(player: str, metric: str, threshold: float, n: int = 0) -> Dict[str, Any]:
    games = _games_for(player, n)
    result = _build_base_rate_signal(
        games,
        metric,
        threshold,
        window=f"last_{n}" if n else "season",
        source="csv",
    )
    if result["signal"] == "unavailable":
        result["details"]["error"] = f"no data for {player}/{metric}"
    return result


def get_role_conditioned_base_stats(
    player: str,
    metric: str,
    threshold: float,
    is_starter: Optional[bool],
    n: int = 0,
) -> Dict[str, Any]:
    if is_starter is None:
        return _signal_payload(
            "unavailable",
            0,
            0,
            0,
            f"last_{n}" if n else "season",
            "csv",
            {"error": "role is unknown; cannot build role-conditioned base stats"},
        )

    role = "starter" if is_starter else "bench"
    role_label = "projected_starter" if is_starter else "projected_bench"
    games = [g for g in _games_for(player, n) if bool(g.get("is_starter")) is is_starter]
    result = _build_base_rate_signal(
        games,
        metric,
        threshold,
        window=f"last_{n}" if n else "season",
        source="csv",
        reliability_min_n=4,
        reliability_full_n=20,
        extra_details={
            "role": role,
            "role_label": role_label,
            "minimum_role_sample": 4,
        },
    )
    if result["signal"] == "unavailable":
        result["details"].update(
            {
                "role": role,
                "role_label": role_label,
                "minimum_role_sample": 4,
                "error": f"no {role} data for {player}/{metric}",
            }
        )
    return result


def get_starter_bench_split(player: str, metric: str, threshold: float) -> Dict[str, Any]:
    all_games = _games_for(player)
    starter = [g for g in all_games if g.get("is_starter")]
    bench = [g for g in all_games if not g.get("is_starter")]

    def _sub(games, label):
        vals = _values(games, metric)
        if not vals:
            return {"label": label, "n": 0}
        r, o, t = _hit_rate(vals, threshold)
        return {"label": label, "n": t, "hit_rate": round(r, 4), "mean": round(statistics.mean(vals), 2)}

    s = _sub(starter, "starter")
    b = _sub(bench, "bench")
    total = s["n"] + b["n"]
    rel = _reliability_from_n(min(s["n"], b["n"]), min_n=5, full_n=20)

    diff = (s.get("mean", 0) or 0) - (b.get("mean", 0) or 0)
    sig = "over" if diff > 2 else ("under" if diff < -2 else "neutral")

    return _signal_payload(sig, diff, total, rel, "season", "csv", {"starter": s, "bench": b})


def get_opponent_history(player: str, metric: str, threshold: float, opponent: str) -> Dict[str, Any]:
    games = [g for g in _games_for(player) if g.get("opponent", "").lower() == opponent.lower()]
    vals = _values(games, metric)
    if not vals:
        return _signal_payload("unavailable", 0, 0, 0, f"vs_{opponent}", "csv", {"error": "no games vs opponent"})

    rate, over, total = _hit_rate(vals, threshold)
    mean = statistics.mean(vals)
    rel = _reliability_from_n(total, min_n=3, full_n=10)
    shrunk = _shrink(rate, total)

    return _signal_payload(_direction(shrunk), mean - threshold, total, rel, f"vs_{opponent}", "csv",
                           {"hit_rate": round(rate, 4), "mean": round(mean, 2), "games": total})


def get_teammate_impact(player: str, metric: str, threshold: float, teammate: str, played: bool) -> Dict[str, Any]:
    all_games = _games_for(player)
    filtered = []
    for g in all_games:
        team = g.get("team", "")
        gd = g.get("game_date")
        if not team or gd is None:
            continue
        lineup = _csv_svc._lineup_cache.get((team, gd.strftime("%Y-%m-%d")), set())
        present = teammate in lineup
        if played and present:
            filtered.append(g)
        elif not played and not present:
            filtered.append(g)

    vals = _values(filtered, metric)
    if not vals:
        label = "with" if played else "without"
        return _signal_payload("unavailable", 0, 0, 0, f"{label}_{teammate}", "csv", {"error": "no matching games"})

    rate, over, total = _hit_rate(vals, threshold)
    mean = statistics.mean(vals)
    rel = _reliability_from_n(total, min_n=5, full_n=25)
    shrunk = _shrink(rate, total)
    label = "with" if played else "without"

    return _signal_payload(_direction(shrunk), mean - threshold, total, rel, f"{label}_{teammate}", "csv",
                           {"hit_rate": round(rate, 4), "shrunk_rate": round(shrunk, 4), "mean": round(mean, 2), "n": total})


# ===================================================================
# DIMENSION 1b – Injury + Teammate Chemistry
# ===================================================================

def _fetch_injury_report_for_team(team_code: str) -> List[Dict[str, Any]]:
    """Scrape ESPN + CBS injury pages, return entries for *team_code*."""
    try:
        from src.sources.injuries_pages import InjuriesPageFetcher
        from src.config import normalize_team_name
    except ImportError:
        return []

    fetcher = InjuriesPageFetcher()
    all_injuries = fetcher.fetch_all()
    result = []
    for _src, injuries in all_injuries.items():
        for inj in injuries:
            if inj.team == team_code:
                result.append({
                    "player": inj.player_name,
                    "position": inj.position,
                    "status": inj.status,
                    "injury": inj.injury,
                    "source": _src,
                })
    return result


def _team_code_from_name(team_name: str) -> str:
    """Best-effort CSV team name -> 3-letter code via nba_lineup_rag."""
    try:
        from src.config import normalize_team_name
        code = normalize_team_name(team_name)
        if code:
            return code
    except ImportError:
        pass
    return team_name


def _today_date_string() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _infer_opponent_from_schedule(player: str, date: str) -> str:
    """
    當 query 未指定對手時，從 The Odds API 賽程推斷對手球隊。
    流程：取得今日賽事 → 逐一查該球員的賠率 → 找到該場即得 home/away，用 CSV 球員所屬隊判斷對手。
    """
    games = _games_for(player)
    if not games:
        return "unknown"
    player_team = games[0].get("team", "")  # CSV 格式如 "Warriors", "Bucks"
    if not player_team:
        return "unknown"

    try:
        from app.services.odds_theoddsapi import odds_provider
    except ImportError:
        return "unknown"

    now = datetime.now(timezone.utc)
    events = await odds_provider.get_events(
        sport="basketball_nba",
        regions="us",
        date_from=now - timedelta(hours=6),
        date_to=now + timedelta(hours=18),
    )
    if not events:
        return "unknown"

    player_code = _team_code_from_name(player_team)
    player_low = player.lower()

    for ev in events:
        try:
            from app.services.odds_gateway import odds_gateway

            snapshot = await odds_gateway.get_market_snapshot(
                sport="basketball_nba",
                event_id=ev["id"],
                regions="us",
                markets="player_points",
                odds_format="american",
                priority="background",
                record_hot_key=False,
            )
            odds = snapshot.data
        except Exception:
            continue
        for bm in odds.get("bookmakers", []):
            for mkt in bm.get("markets", []):
                for o in mkt.get("outcomes", []):
                    if o.get("description", "").lower() == player_low:
                        home = ev.get("home_team", "")
                        away = ev.get("away_team", "")
                        home_code = _team_code_from_name(home)
                        away_code = _team_code_from_name(away)
                        if home_code == player_code:
                            return away
                        if away_code == player_code:
                            return home
                        return "unknown"
    return "unknown"


async def get_official_injury_report(team: str, date: str = "", player: str = "") -> Dict[str, Any]:
    # 當 query 未指定對手時，從 The Odds API 賽程推斷
    effective_team = team
    if (not team or team == "unknown") and player:
        effective_team = await _infer_opponent_from_schedule(player, date)
        if effective_team == "unknown":
            effective_team = team or "unknown"  # 保持原值以便 details 顯示

    code = _team_code_from_name(effective_team)
    entries = await asyncio.to_thread(_fetch_injury_report_for_team, code)
    return _signal_payload(
        "caution" if entries else "neutral",
        0.0,
        len(entries),
        0.9 if entries else 0.5,
        "today",
        "official_injury_report",
        {"team": effective_team, "team_code": code, "injuries": entries},
    )


async def get_projected_lineup_consensus(team: str, date: str = "") -> Dict[str, Any]:
    try:
        from app.services.lineup_service import lineup_service
    except ImportError:
        return _signal_payload("unavailable", 0, 0, 0.0, "today", "lineup_consensus", {"error": "service unavailable"})

    effective_date = date or _today_date_string()
    code = _team_code_from_name(team)
    lineup, cache_state, _fetched_at = await lineup_service.get_team_lineup(effective_date, code)
    if not lineup:
        return _signal_payload(
            "unavailable",
            0,
            0,
            0.0,
            "today",
            "lineup_consensus",
            {"team": team, "team_code": code, "cache_state": cache_state},
        )

    updated_at = lineup.get("updated_at")
    freshness_minutes = None
    if updated_at:
        try:
            parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            freshness_minutes = int((datetime.now(timezone.utc) - parsed).total_seconds() / 60)
        except ValueError:
            freshness_minutes = None

    confidence = lineup.get("confidence")
    reliability = {
        "high": 0.85,
        "medium": 0.7,
        "low": 0.55,
    }.get(confidence, 0.4)
    signal = "caution" if lineup.get("status") != "projected" or lineup.get("source_disagreement") else "neutral"

    return _signal_payload(
        signal,
        0.0,
        len(lineup.get("starters") or []),
        reliability,
        "today",
        "lineup_consensus",
        {
            **lineup,
            "team_code": code,
            "cache_state": cache_state,
            "freshness_minutes": freshness_minutes,
        },
    )


async def get_player_lineup_context(player: str, date: str = "", team: str = "", opponent: str = "") -> Dict[str, Any]:
    target_team = team
    if not target_team:
        games = _games_for(player, 1)
        if games:
            target_team = games[0].get("team", "")

    own_lineup = await get_projected_lineup_consensus(target_team, date)
    opponent_lineup = await get_projected_lineup_consensus(opponent, date) if opponent else _signal_payload(
        "neutral", 0, 0, 0.0, "today", "lineup_consensus", {}
    )

    own_details = own_lineup.get("details", {}) if isinstance(own_lineup, dict) else {}
    starters = list(own_details.get("starters") or [])
    team_code = own_details.get("team") or _team_code_from_name(target_team)
    canonical_player_name = None
    try:
        from app.services.lineup_source_support import resolve_canonical_player_name

        canonical_player_name = resolve_canonical_player_name(player, team_code).get("canonical_name")
    except ImportError:
        canonical_player_name = None

    player_match_value = (canonical_player_name or player).lower()
    has_complete_projected_lineup = own_details.get("status") == "projected" and len(starters) == 5
    player_matches_starter = any(player_match_value == starter.lower() for starter in starters)
    if player_matches_starter:
        player_is_projected_starter = True
    elif has_complete_projected_lineup and canonical_player_name:
        player_is_projected_starter = False
    else:
        player_is_projected_starter = None
    freshness_minutes = own_details.get("freshness_minutes")
    freshness_risk = isinstance(freshness_minutes, int) and freshness_minutes > 20
    source_disagreement = bool(own_details.get("source_disagreement"))
    confidence = own_details.get("confidence")

    signal = "positive"
    if not starters:
        signal = "unavailable"
    elif player_is_projected_starter is False or source_disagreement or freshness_risk or not has_complete_projected_lineup:
        signal = "caution"

    return _signal_payload(
        signal,
        0.0,
        len(starters),
        {
            "high": 0.85,
            "medium": 0.7,
            "low": 0.55,
        }.get(confidence, 0.4),
        "today",
        "lineup_consensus",
        {
            "player": player,
            "team": team_code,
            "canonical_player_name": canonical_player_name,
            "player_is_projected_starter": player_is_projected_starter,
            "source_disagreement": source_disagreement,
            "freshness_risk": freshness_risk,
            "freshness_minutes": freshness_minutes,
            "confidence": confidence,
            "status": own_details.get("status"),
            "starters": starters,
            "player_team_lineup": own_details,
            "opponent_team_lineup": opponent_lineup.get("details", {}),
        },
    )


def get_availability_context(player: str, date: str = "") -> Dict[str, Any]:
    games = _games_for(player, 10)
    if not games:
        return _signal_payload("unavailable", 0, 0, 0, "last_10", "csv", {"error": "no games"})
    team = games[0].get("team", "")
    code = _team_code_from_name(team)
    injuries = _fetch_injury_report_for_team(code)
    player_low = player.lower()
    player_entry = next((e for e in injuries if player_low in e["player"].lower()), None)
    status = player_entry["status"] if player_entry else "Healthy"
    return _signal_payload(
        "caution" if status in ("Out", "Questionable", "Day-To-Day") else "neutral",
        0.0, 1, 0.9 if player_entry else 0.6, "today", "official_injury_report",
        {"player": player, "status": status, "detail": player_entry},
    )


def _position_group(pos: str) -> str:
    pos = pos.upper().strip()
    if pos in ("PG", "SG"):
        return "backcourt"
    return "frontcourt"


def auto_teammate_impact(player: str, metric: str, threshold: float) -> Dict[str, Any]:
    games = _games_for(player)
    if not games:
        return _signal_payload("unavailable", 0, 0, 0, "season", "csv", {"error": "no data"})

    team = games[0].get("team", "")
    player_pos = games[0].get("pos", "")
    stars = _STAR_PLAYERS.get(team, [])
    stars = [s for s in stars if s.lower() != player.lower()]

    if not stars:
        return _signal_payload("neutral", 0, 0, 0.3, "season", "csv", {"note": "no star teammates registered"})

    code = _team_code_from_name(team)
    injuries = _fetch_injury_report_for_team(code)
    injury_map = {}
    for e in injuries:
        injury_map[e["player"].lower()] = e

    chemistry = []
    for star in stars:
        with_data = get_teammate_impact(player, metric, threshold, star, played=True)
        without_data = get_teammate_impact(player, metric, threshold, star, played=False)

        w_mean = with_data["details"].get("mean", 0) or 0
        wo_mean = without_data["details"].get("mean", 0) or 0
        delta = round(w_mean - wo_mean, 2)

        star_injury = injury_map.get(star.lower())
        inj_status = star_injury["status"] if star_injury else "Healthy"
        inj_detail = star_injury.get("injury", "") if star_injury else ""

        star_games_sample = _games_for(star, 5)
        star_pos = star_games_sample[0].get("pos", "") if star_games_sample else ""
        pg_match = _position_group(player_pos) == _position_group(star_pos) if player_pos and star_pos else None

        interp = "target performs better WITH this star" if delta > 0 else "target performs better WITHOUT this star (usage redistribution)"

        chemistry.append({
            "star": star,
            "position": star_pos,
            "position_group_match": pg_match,
            "injury_status": inj_status,
            "injury_detail": inj_detail,
            "with": with_data["details"],
            "without": without_data["details"],
            "chemistry_delta": delta,
            "interpretation": interp,
        })

    active_stars = [c["star"] for c in chemistry if c["injury_status"] in ("Healthy", "Probable")]
    out_stars = [c["star"] for c in chemistry if c["injury_status"] in ("Out", "Questionable", "Day-To-Day")]
    scenario = f"Active: {', '.join(active_stars) or 'none'}; Out/Questionable: {', '.join(out_stars) or 'none'}"

    min_n = min(
        (c["with"].get("n", 0) for c in chemistry if c["with"].get("n")),
        default=0,
    )
    rel = _reliability_from_n(min_n, min_n=5, full_n=25)

    return _signal_payload(
        "caution" if out_stars else "neutral",
        0.0,
        sum(c["with"].get("n", 0) + c["without"].get("n", 0) for c in chemistry),
        rel,
        "season",
        "csv+official_injury_report",
        {
            "team": team,
            "team_code": code,
            "player_position": player_pos,
            "teammate_chemistry": chemistry,
            "today_scenario": scenario,
        },
    )


# ===================================================================
# DIMENSION 2 – Form / Trend / Role Change
# ===================================================================

def get_trend_analysis(player: str, metric: str) -> Dict[str, Any]:
    games = _games_for(player)
    vals = _values(games, metric)
    if len(vals) < 5:
        return _signal_payload("unavailable", 0, len(vals), 0, "season", "csv", {"error": "not enough games"})

    def _avg(v, n):
        return round(statistics.mean(v[:n]), 2) if len(v) >= n else None

    season_avg = round(statistics.mean(vals), 2)
    avgs = {f"last_{w}": _avg(vals, w) for w in (3, 5, 10, 20)}
    recent = avgs["last_5"] or season_avg
    diff = recent - season_avg
    pct = diff / season_avg if season_avg else 0

    if pct > 0.10:
        sig = "over"
    elif pct < -0.10:
        sig = "under"
    else:
        sig = "neutral"

    return _signal_payload(sig, diff, len(vals), _reliability_from_n(len(vals)), "season", "csv",
                           {"rolling_averages": avgs, "season_avg": season_avg, "recent_vs_season_pct": round(pct, 4)})


def get_streak_info(player: str, metric: str, threshold: float) -> Dict[str, Any]:
    games = _games_for(player)
    vals = _values(games, metric)
    if not vals:
        return _signal_payload("unavailable", 0, 0, 0, "season", "csv", {"error": "no data"})

    streak, streak_dir, longest_over, longest_under = 0, None, 0, 0
    cur_over, cur_under = 0, 0
    for v in vals:
        if v > threshold:
            cur_over += 1
            cur_under = 0
        else:
            cur_under += 1
            cur_over = 0
        longest_over = max(longest_over, cur_over)
        longest_under = max(longest_under, cur_under)

    cur_over, cur_under = 0, 0
    for v in vals:
        if v > threshold:
            cur_over += 1
            if cur_under > 0:
                break
            cur_under = 0
        else:
            cur_under += 1
            if cur_over > 0:
                break
            cur_over = 0

    streak = cur_over if cur_over else -cur_under
    sig = "over" if streak >= 3 else ("under" if streak <= -3 else "neutral")

    return _signal_payload(sig, float(streak), len(vals), _reliability_from_n(len(vals)), "season", "csv",
                           {"current_streak": streak, "longest_over_streak": longest_over, "longest_under_streak": longest_under})


def get_minutes_role_trend(player: str) -> Dict[str, Any]:
    games = _games_for(player)
    mins = _values(games, "minutes")
    if len(mins) < 5:
        return _signal_payload("unavailable", 0, len(mins), 0, "season", "csv", {"error": "not enough games"})

    season_avg = statistics.mean(mins)
    last5 = statistics.mean(mins[:5])
    last10 = statistics.mean(mins[:10]) if len(mins) >= 10 else None
    starter_pct = sum(1 for g in games[:10] if g.get("is_starter")) / min(len(games), 10)
    diff = last5 - season_avg

    sig = "over" if diff > 2 else ("under" if diff < -2 else "neutral")
    return _signal_payload(sig, diff, len(mins), _reliability_from_n(len(mins)), "season", "csv",
                           {"season_avg_min": round(season_avg, 1), "last5_avg_min": round(last5, 1),
                            "last10_avg_min": round(last10, 1) if last10 else None,
                            "starter_pct_last10": round(starter_pct, 2)})


def get_usage_touches_profile(player: str, date: str = "") -> Dict[str, Any]:
    games = _games_for(player, 20)
    if len(games) < 5:
        return _signal_payload("unavailable", 0, len(games), 0, "last_20", "csv", {"error": "not enough games"})

    fga_vals = _values(games, "fga")
    fta_vals = _values(games, "fta")
    min_vals = _values(games, "minutes")
    ast_vals = _values(games, "assists")

    fga_per_min = [a / m for a, m in zip(fga_vals, min_vals) if m and m > 0] if fga_vals and min_vals else []
    recent_fga_pm = statistics.mean(fga_per_min[:5]) if len(fga_per_min) >= 5 else None
    season_fga_pm = statistics.mean(fga_per_min) if fga_per_min else None

    diff = (recent_fga_pm - season_fga_pm) if recent_fga_pm and season_fga_pm else 0
    sig = "over" if diff > 0.05 else ("under" if diff < -0.05 else "neutral")

    return _signal_payload(sig, diff or 0, len(games), _reliability_from_n(len(games)), "last_20", "csv",
                           {"fga_per_min_last5": round(recent_fga_pm, 3) if recent_fga_pm else None,
                            "fga_per_min_season": round(season_fga_pm, 3) if season_fga_pm else None,
                            "avg_fta_last5": round(statistics.mean(fta_vals[:5]), 1) if len(fta_vals) >= 5 else None,
                            "avg_ast_last5": round(statistics.mean(ast_vals[:5]), 1) if len(ast_vals) >= 5 else None})


def get_opportunity_profile(player: str, metric: str, date: str = "") -> Dict[str, Any]:
    games = _games_for(player, 20)
    vals = _values(games, metric)
    mins = _values(games, "minutes")
    if len(vals) < 5 or len(mins) < 5:
        return _signal_payload("unavailable", 0, len(vals), 0, "last_20", "csv", {"error": "not enough data"})

    per_min = [v / m for v, m in zip(vals, mins) if m and m > 0]
    recent_rate = statistics.mean(per_min[:5]) if len(per_min) >= 5 else None
    full_rate = statistics.mean(per_min) if per_min else None

    diff = (recent_rate - full_rate) if recent_rate and full_rate else 0
    sig = "over" if diff > 0.02 else ("under" if diff < -0.02 else "neutral")

    return _signal_payload(sig, diff or 0, len(vals), _reliability_from_n(len(vals)), "last_20", "csv",
                           {"per_min_last5": round(recent_rate, 4) if recent_rate else None,
                            "per_min_full": round(full_rate, 4) if full_rate else None,
                            "note": "rate expanding" if diff and diff > 0 else "stable or declining"})


# ===================================================================
# DIMENSION 3 – Shooting Efficiency
# ===================================================================

def get_shooting_profile(player: str) -> Dict[str, Any]:
    games = _games_for(player)
    if len(games) < 5:
        return _signal_payload("unavailable", 0, len(games), 0, "season", "csv", {"error": "not enough games"})

    def _pct(made, att):
        return round(sum(m for m in made if m is not None) / max(sum(a for a in att if a is not None), 1), 3)

    def _slice(games_list, n=None):
        g = games_list[:n] if n else games_list
        return {
            "fg_pct": _pct(_values(g, "fgm"), _values(g, "fga")),
            "tp_pct": _pct(_values(g, "tpm"), _values(g, "tpa")),
            "ft_pct": _pct(_values(g, "ftm"), _values(g, "fta")),
            "avg_fta": round(statistics.mean(_values(g, "fta") or [0]), 1),
            "n": len(g),
        }

    season = _slice(games)
    last5 = _slice(games, 5)
    fg_diff = last5["fg_pct"] - season["fg_pct"]

    flags = []
    if fg_diff > 0.06:
        flags.append("hot_shooting_regression_risk")
    if fg_diff < -0.06:
        flags.append("cold_shooting_bounce_back")
    if last5["avg_fta"] > season["avg_fta"] + 1.5:
        flags.append("fta_spike_aggression")

    sig = "caution" if "hot_shooting_regression_risk" in flags else "neutral"
    return _signal_payload(sig, fg_diff, len(games), _reliability_from_n(len(games)), "season", "csv",
                           {"season": season, "last_5": last5, "fg_diff": round(fg_diff, 3), "flags": flags})


def get_shooting_mix_profile(player: str, date: str = "") -> Dict[str, Any]:
    games = _games_for(player, 20)
    if len(games) < 5:
        return _signal_payload("unavailable", 0, len(games), 0, "last_20", "csv", {"error": "not enough"})

    fga_vals = [g.get("fga") or 0 for g in games]
    tpa_vals = [g.get("tpa") or 0 for g in games]
    fta_vals = [g.get("fta") or 0 for g in games]

    three_share = [t / a if a else 0 for t, a in zip(tpa_vals, fga_vals)]
    recent_3share = statistics.mean(three_share[:5])
    season_3share = statistics.mean(three_share)

    diff = recent_3share - season_3share
    sig = "neutral"
    if diff > 0.05:
        sig = "caution"

    return _signal_payload(sig, diff, len(games), _reliability_from_n(len(games)), "last_20", "csv",
                           {"three_point_share_last5": round(recent_3share, 3),
                            "three_point_share_season": round(season_3share, 3),
                            "avg_fta_last5": round(statistics.mean(fta_vals[:5]), 1)})


# ===================================================================
# DIMENSION 4 – Variance / Consistency
# ===================================================================

def get_variance_profile(player: str, metric: str) -> Dict[str, Any]:
    games = _games_for(player)
    vals = _values(games, metric)
    if len(vals) < 5:
        return _signal_payload("unavailable", 0, len(vals), 0, "season", "csv", {"error": "not enough"})

    mean = statistics.mean(vals)
    std = statistics.stdev(vals) if len(vals) > 1 else 0.0
    cv = std / mean if mean else 0.0
    sorted_v = sorted(vals)
    n = len(sorted_v)
    p10 = sorted_v[max(int(n * 0.1) - 1, 0)]
    p50 = sorted_v[n // 2]
    p90 = sorted_v[min(int(n * 0.9), n - 1)]

    sig = "caution" if cv > 0.4 else "neutral"
    return _signal_payload(sig, cv, n, _reliability_from_n(n), "season", "csv",
                           {"mean": round(mean, 2), "std": round(std, 2), "cv": round(cv, 3),
                            "p10": round(p10, 1), "p50": round(p50, 1), "p90": round(p90, 1)})


# ===================================================================
# DIMENSION 5 – Schedule / Context
# ===================================================================

def get_schedule_context(player: str, date: str = "") -> Dict[str, Any]:
    games = _games_for(player)
    if not games:
        return _signal_payload("unavailable", 0, 0, 0, "season", "csv", {"error": "no data"})

    dates = [g["game_date"] for g in games if g.get("game_date")]
    if len(dates) < 2:
        return _signal_payload("neutral", 0, len(dates), 0.3, "season", "csv", {"note": "not enough date info"})

    last_date = dates[0]
    target = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now()
    days_rest = (target - last_date).days if last_date else None

    rest_buckets: Dict[str, List[float]] = {"b2b": [], "short": [], "normal": []}
    min_vals = _values(games, "minutes")
    for i in range(len(dates) - 1):
        gap = (dates[i] - dates[i + 1]).days
        bucket = "b2b" if gap <= 1 else ("short" if gap == 2 else "normal")
        if i < len(min_vals):
            rest_buckets[bucket].append(min_vals[i])

    avg_by_rest = {k: round(statistics.mean(v), 1) if v else None for k, v in rest_buckets.items()}
    is_b2b = days_rest is not None and days_rest <= 1

    sig = "caution" if is_b2b else "neutral"
    return _signal_payload(sig, 0, len(games), _reliability_from_n(len(games)), "today", "csv",
                           {"days_rest": days_rest, "is_back_to_back": is_b2b,
                            "avg_minutes_by_rest": avg_by_rest})


def get_game_script_splits(player: str, metric: str, threshold: float) -> Dict[str, Any]:
    games = _games_for(player)
    wins = [g for g in games if g.get("wl", "").upper() == "W"]
    losses = [g for g in games if g.get("wl", "").upper() == "L"]

    def _sub(gl, label):
        vals = _values(gl, metric)
        if not vals:
            return {"label": label, "n": 0}
        r, o, t = _hit_rate(vals, threshold)
        return {"label": label, "n": t, "hit_rate": round(r, 4), "mean": round(statistics.mean(vals), 2)}

    w = _sub(wins, "win")
    l = _sub(losses, "loss")
    total = w["n"] + l["n"]
    diff = (w.get("mean", 0) or 0) - (l.get("mean", 0) or 0)
    sig = "neutral"
    if abs(diff) > 3:
        sig = "caution"

    return _signal_payload(sig, diff, total, _reliability_from_n(min(w["n"], l["n"]), 5, 20), "season", "csv",
                           {"wins": w, "losses": l, "diff": round(diff, 2)})


def get_lineup_context(player: str, date: str = "") -> Dict[str, Any]:
    games = _games_for(player, 10)
    if not games:
        return _signal_payload("unavailable", 0, 0, 0, "last_10", "csv", {"error": "no data"})

    team = games[0].get("team", "")
    lineups = []
    for g in games:
        gd = g.get("game_date")
        if gd and team:
            lineup = _csv_svc._lineup_cache.get((team, gd.strftime("%Y-%m-%d")), set())
            lineups.append(lineup)

    if not lineups:
        return _signal_payload("neutral", 0, 0, 0.3, "last_10", "csv", {"note": "no lineup data"})

    from collections import Counter
    all_mates = Counter()
    for lu in lineups:
        lu_copy = lu - {player}
        all_mates.update(lu_copy)

    frequent = [(name, cnt) for name, cnt in all_mates.most_common(8)]
    return _signal_payload("neutral", 0, len(lineups), _reliability_from_n(len(lineups), 3, 10), "last_10", "csv",
                           {"team": team, "games_sampled": len(lineups), "frequent_teammates": frequent})


def get_rotation_absorption_map(player: str, metric: str, date: str = "") -> Dict[str, Any]:
    games = _games_for(player)
    if not games:
        return _signal_payload("unavailable", 0, 0, 0, "season", "csv", {"error": "no data"})

    team = games[0].get("team", "")
    stars = _STAR_PLAYERS.get(team, [])
    stars = [s for s in stars if s.lower() != player.lower()]

    if not stars:
        return _signal_payload("neutral", 0, 0, 0.3, "season", "csv", {"note": "no tracked stars"})

    absorptions = []
    for star in stars:
        with_data = get_teammate_impact(player, metric, 0, star, played=True)
        without_data = get_teammate_impact(player, metric, 0, star, played=False)
        w_mean = with_data["details"].get("mean", 0) or 0
        wo_mean = without_data["details"].get("mean", 0) or 0
        absorptions.append({
            "absent_star": star,
            "player_mean_with": round(w_mean, 2),
            "player_mean_without": round(wo_mean, 2),
            "absorption_delta": round(wo_mean - w_mean, 2),
        })

    return _signal_payload("neutral", 0, len(games), _reliability_from_n(len(games)), "season", "csv",
                           {"team": team, "absorptions": absorptions})


# ===================================================================
# Registry – all tools for LangChain binding
# ===================================================================

ALL_HISTORICAL_TOOLS = [
    get_base_stats,
    get_role_conditioned_base_stats,
    get_starter_bench_split,
    get_opponent_history,
    get_teammate_impact,
    get_official_injury_report,
    get_projected_lineup_consensus,
    get_player_lineup_context,
    get_availability_context,
    auto_teammate_impact,
    get_trend_analysis,
    get_streak_info,
    get_minutes_role_trend,
    get_usage_touches_profile,
    get_opportunity_profile,
    get_shooting_profile,
    get_shooting_mix_profile,
    get_variance_profile,
    get_schedule_context,
    get_game_script_splits,
    get_lineup_context,
    get_rotation_absorption_map,
]
