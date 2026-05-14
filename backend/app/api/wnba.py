"""
wnba.py - WNBA related API endpoints (Phase 1 SPO-32 + Phase 2 SPO-33)

Sibling of backend/app/api/nba.py. The file groups WNBA endpoints by phase:

Phase 1 (SPO-32) — read-only data layer:
1. GET  /api/wnba/csv/players         — paginated player listing
2. POST /api/wnba/csv/reload          — admin cache reload
3. GET  /api/wnba/player-history      — per-player game log + Over/Under
4. GET  /api/wnba/player-dd-history   — per-player Double-Double rate

Phase 2 (SPO-33) — live odds layer:
5. GET  /api/wnba/events              — WNBA events for a date
6. POST /api/wnba/props/no-vig        — no-vig calc (Over/Under + DD-binary)
7. GET  /api/wnba/players/suggest     — autocomplete from a live event's odds snapshot

💡 Design (Phase 2):
- Reuses the already-parameterized `odds_gateway` / `odds_provider` —
  `OddsMarketGateway.get_market_snapshot` accepts `sport: str` and embeds
  it in the snapshot cache key, so no fork is needed (CLAUDE.md §
  "One gateway, one provider, parameterized").
- The 9 hard-supported WNBA markets (Phase 0 / SPO-31 evidence) all share
  NBA's Over/Under outcome shape, so the standard parser ports 1:1.
  `player_double_double` uses the DD-binary path proven in SPO-26.
- The 3 schema-valid+empty markets (`player_steals`, `player_blocks`,
  `player_turnovers`) are handled by the existing empty-bookmakers UX
  from SPO-26 — no extra branch, no crash.

⚠ Anti-hallucination: do NOT add a market key to the WNBA route unless
Phase 0's research doc (`docs/research/wnba-rollout/odds_api_wnba_markets.md`)
classified it as `hard-supported` or `schema-valid+empty`. Unknown keys
return empty `bookmakers=[]` silently, which reads as "no lines" rather
than an error.

🔗 Drift-risk note: the Phase 2 no-vig handler is a **high-fidelity port** of
`nba.py`'s Over/Under and DD-binary bodies — duplicated rather than factored
out to preserve the SPO-33 acceptance criterion "existing NBA path unchanged."
One deliberate divergence: the WNBA handler uses
`(outcome.get("name") or "").lower()` so a `{"name": null}` payload from The
Odds API degrades to an empty-string skip rather than crashing on
`AttributeError` (the NBA form `outcome.get("name", "").lower()` would crash).
Functional behaviour is otherwise identical. When a 3rd league joins, factor
the shared helpers (`_collect_player_names`, `_snapshot_metadata`,
`_build_binary_no_vig_response`) into `app.services.no_vig_helpers` —
rule-of-three lives at 3, not 2. When that extraction happens, apply the
WNBA hardening to NBA in the same PR so the two parsers stay aligned.
"""

from datetime import datetime, time, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.middleware.rate_limit import limiter
from app.models.schemas import (
    BookmakerResult,
    Consensus,
    CSVPlayersResponse,
    EventsResponse,
    GameLog,
    HistogramBin,
    NBAEvent,
    NoVigRequest,
    NoVigResponse,
    PlayerDDHistoryResponse,
    PlayerHistoryResponse,
    PlayerSuggestResponse,
)
from app.services.cache import CacheService, cache_service
from app.services.csv_player_history import (
    CONTINUOUS_METRIC_EXTRACTORS,
    wnba_csv_player_service,
)
from app.services.normalize import (
    find_player,
    suggest_players as suggest_player_names,
)
from app.services.odds_gateway import MarketSnapshotResult, odds_gateway
from app.services.odds_provider import OddsAPIError
from app.services.odds_snapshot_service import BINARY_MARKET_KEYS
from app.services.odds_theoddsapi import odds_provider
from app.services.prob import (
    DEFAULT_BINARY_VIG,
    american_to_prob,
    calculate_consensus_mean,
    calculate_vig,
    devig,
    single_leg_devig,
)
from app.settings import settings


# The Odds API sport key for WNBA — verified by Phase 0 (SPO-31).
WNBA_SPORT_KEY = "basketball_wnba"

# Same binary-line sentinel as nba.py. The DD market has no real
# bookmaker threshold; 0.5 is the convention `odds_snapshot_service.
# _parse_binary_market` writes to the DB, mirrored here so /props/no-vig
# responses for DD agree with any future snapshot-stored rows.
_BINARY_LINE_SENTINEL = 0.5


router = APIRouter(prefix="/api/wnba", tags=["wnba"])


@router.get(
    "/csv/players",
    response_model=CSVPlayersResponse,
    summary="Get WNBA CSV player list",
    description="Get all WNBA player names from the CSV file (for autocomplete)",
)
async def get_csv_players(
    q: str = Query(default="", description="Search keyword (case-insensitive)"),
) -> CSVPlayersResponse:
    """Get WNBA player names from data/wnba_player_game_logs.csv."""
    try:
        players = wnba_csv_player_service.get_all_players(search=q if q else None)
        return CSVPlayersResponse(players=players, total=len(players))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read WNBA CSV: {str(e)}")


@router.post(
    "/csv/reload",
    summary="Reload WNBA CSV data",
    description="Force clear cache and reload the WNBA CSV file",
)
async def reload_csv():
    """Force reload WNBA CSV data."""
    try:
        wnba_csv_player_service.reload()
        return {
            "success": True,
            "message": "WNBA CSV data reloaded",
            "total_players": len(wnba_csv_player_service.get_all_players()),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"WNBA CSV reload failed: {str(e)}")


@router.get(
    "/player-history",
    response_model=PlayerHistoryResponse,
    summary="Get WNBA player historical stats",
    description="Calculate empirical probability and distribution for a WNBA player's historical data on a specified metric.",
)
async def get_player_history(
    player: str = Query(..., description="Player name"),
    metric: str = Query(default="points", description="Stat metric: points, assists, rebounds, pra, etc."),
    threshold: float = Query(..., description="Threshold (e.g. 20.5)"),
    n: int = Query(default=0, ge=0, description="Last N games, 0 means all"),
    bins: int = Query(default=15, ge=5, le=50, description="Histogram bins (5-50)"),
    exclude_dnp: bool = Query(default=True, description="Exclude DNP (Did Not Play, 0 minutes) games"),
    opponent: Optional[str] = Query(default=None, description="Opponent filter (team name), None means all"),
    is_starter: Optional[bool] = Query(default=None, description="Starter filter"),
    teammate_filter: Optional[str] = Query(default=None, description="Comma-separated teammate names"),
    teammate_played: Optional[bool] = Query(default=None, description="Teammate played filter"),
) -> PlayerHistoryResponse:
    """Get WNBA player historical statistical summary."""
    valid_metrics = sorted(CONTINUOUS_METRIC_EXTRACTORS.keys())
    if metric not in valid_metrics:
        hint = ""
        if metric in ("dd", "double_double"):
            hint = " — DD is binary; use GET /api/wnba/player-dd-history instead."
        raise HTTPException(status_code=400, detail=f"Invalid metric: {metric}. Valid: {valid_metrics}{hint}")

    try:
        teammate_list = None
        if teammate_filter:
            teammate_list = [t.strip() for t in teammate_filter.split(",") if t.strip()]

        stats = wnba_csv_player_service.get_player_stats(
            player_name=player,
            metric=metric,
            threshold=threshold,
            n=n,
            bins=bins,
            exclude_dnp=exclude_dnp,
            opponent=opponent,
            is_starter=is_starter,
            teammate_filter=teammate_list,
            teammate_played=teammate_played,
        )

        histogram_bins = [
            HistogramBin(binStart=b["binStart"], binEnd=b["binEnd"], count=b["count"])
            for b in stats.get("histogram", [])
        ]
        game_logs = [
            GameLog(
                date=log["date"],
                date_full=log["date_full"],
                opponent=log["opponent"],
                value=log["value"],
                is_over=log["is_over"],
                team=log.get("team", ""),
                minutes=log.get("minutes", 0.0),
                is_starter=log.get("is_starter", False),
            )
            for log in stats.get("game_logs", [])
        ]

        return PlayerHistoryResponse(
            player=stats["player"],
            metric=stats["metric"],
            threshold=stats["threshold"],
            n_games=stats["n_games"],
            p_over=stats["p_over"],
            p_under=stats["p_under"],
            equal_count=stats.get("equal_count", 0),
            mean=stats["mean"],
            std=stats["std"],
            histogram=histogram_bins,
            game_logs=game_logs,
            opponents=stats.get("opponents", []),
            teammates=stats.get("teammates", []),
            opponent_filter=stats.get("opponent_filter"),
            teammate_filter=stats.get("teammate_filter"),
            teammate_played=stats.get("teammate_played"),
            message=stats.get("message"),
        )

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"WNBA player history calculation failed: {str(e)}")


@router.get(
    "/player-dd-history",
    response_model=PlayerDDHistoryResponse,
    summary="Get WNBA player Double-Double historical rate",
    description="Compute historical P(DD = 1) for a WNBA player. DD is binary (Yes/No), no threshold.",
)
async def get_player_dd_history(
    player: str = Query(..., description="Player name (fuzzy-matched if exact match fails)"),
    season: Optional[str] = Query(default=None, description="Season filter; None means all seasons"),
) -> PlayerDDHistoryResponse:
    """Get WNBA player Double-Double historical rate."""
    try:
        stats = wnba_csv_player_service.player_dd_history(player_name=player, season=season)
        return PlayerDDHistoryResponse(
            player=stats["player"],
            season=stats.get("season"),
            n_games=stats.get("n_games", 0),
            dd_games=stats.get("dd_games", 0),
            prob_dd=stats.get("prob_dd"),
            message=stats.get("message"),
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"WNBA DD history calculation failed: {str(e)}")


# ==================== Phase 2 — Live odds layer (SPO-33) =====================
#
# Helpers below are a high-fidelity port of `nba.py` — duplicated rather than
# factored out so SPO-33's acceptance criterion "existing NBA path unchanged"
# holds. One deliberate divergence (null-safe `name` parsing) is documented in
# the module docstring; functional behaviour is otherwise identical.


def _snapshot_metadata(snapshot: MarketSnapshotResult) -> dict:
    return {
        "fetched_at": snapshot.fetched_at,
        "data_age_seconds": snapshot.data_age_seconds,
        "cache_state": snapshot.cache_state,
        "source": snapshot.source,
    }


def _collect_player_names(
    bookmakers_data: list[dict],
    market_key: str,
) -> list[str]:
    player_set = set()
    for bookmaker in bookmakers_data:
        for market in bookmaker.get("markets", []):
            if market.get("key") != market_key:
                continue
            for outcome in market.get("outcomes", []):
                if "description" in outcome:
                    player_set.add(outcome["description"])
    return sorted(player_set)


def _build_binary_no_vig_response(
    body: NoVigRequest,
    snapshot: MarketSnapshotResult,
    bookmakers_data: list[dict],
    matched_player: str,
) -> NoVigResponse:
    """
    Build a NoVigResponse for a binary Yes/No market (e.g. DD).

    High-fidelity port of `nba.py._build_binary_no_vig_response`:
    - Requires the Yes leg per bookmaker; rows where only "No" is posted
      are dropped (no honest single-leg anchor).
    - Two-leg path uses `devig(p_yes_imp, p_no_imp)`.
    - Single-leg (Yes only) path uses
      `single_leg_devig(p_yes_imp, DEFAULT_BINARY_VIG)`. If the prior cannot
      be safely applied (extreme prices), the row is dropped and counted in
      `rows_dropped_due_to_prior` — surfaced in the aggregate message so the
      omission is visible rather than fabricated.
    - Legacy `over_*/under_*` fields encode "over=Yes, under=No" so existing
      frontend Zod parsers keep working; explicit `yes_*/no_*` mirrors are
      populated alongside for SPO-26-aware consumers.
    - `Consensus.p_yes_fair/p_no_fair` mirrors are populated for binary.

    Deliberate divergence from `nba.py` — null-safe `name` parsing
    (`(outcome.get("name") or "").lower()` vs NBA's
    `outcome.get("name", "").lower()`): degrades a `{"name": null}` payload
    to an empty-string skip rather than crashing on `AttributeError`. See
    the module docstring drift-risk note for the alignment plan when the
    rule-of-three extraction lands.
    """
    results: List[BookmakerResult] = []
    fair_probs_for_consensus: List[tuple] = []
    rows_dropped_due_to_prior = 0

    for bookmaker in bookmakers_data:
        bookmaker_key = bookmaker.get("key", "unknown")

        for market in bookmaker.get("markets", []):
            if market.get("key") != body.market:
                continue

            yes_outcome: Optional[dict] = None
            no_outcome: Optional[dict] = None
            for outcome in market.get("outcomes", []):
                if outcome.get("description") != matched_player:
                    continue
                outcome_name = (outcome.get("name") or "").lower()
                if outcome_name == "yes":
                    yes_outcome = outcome
                elif outcome_name == "no":
                    no_outcome = outcome

            # Without a Yes price there is nothing to anchor any de-vig
            # calculation on; skip rather than fabricate.
            if yes_outcome is None:
                continue

            yes_price = yes_outcome.get("price", 0)
            if yes_price == 0:
                continue
            no_price_raw = no_outcome.get("price", 0) if no_outcome is not None else 0

            try:
                p_yes_imp = american_to_prob(yes_price)
                no_price: Optional[float]
                p_no_imp: Optional[float]

                if no_price_raw != 0:
                    no_price = float(no_price_raw)
                    p_no_imp = american_to_prob(no_price_raw)
                    vig = calculate_vig(p_yes_imp, p_no_imp)
                    p_yes_fair, p_no_fair = devig(p_yes_imp, p_no_imp)
                else:
                    no_price = None
                    p_no_imp = None
                    p_yes_fair = single_leg_devig(p_yes_imp, DEFAULT_BINARY_VIG)
                    if p_yes_fair is None:
                        rows_dropped_due_to_prior += 1
                        continue
                    p_no_fair = 1.0 - p_yes_fair
                    vig = DEFAULT_BINARY_VIG

                under_odds_for_legacy = (
                    float(no_price) if no_price is not None else float(yes_price)
                )
                p_under_imp_for_legacy = (
                    p_no_imp if p_no_imp is not None else (1.0 - p_yes_imp)
                )

                results.append(
                    BookmakerResult(
                        bookmaker=bookmaker_key,
                        line=_BINARY_LINE_SENTINEL,
                        over_odds=float(yes_price),
                        under_odds=under_odds_for_legacy,
                        p_over_imp=round(p_yes_imp, 4),
                        p_under_imp=round(p_under_imp_for_legacy, 4),
                        vig=round(vig, 4),
                        p_over_fair=round(p_yes_fair, 4),
                        p_under_fair=round(p_no_fair, 4),
                        fetched_at=snapshot.fetched_at,
                        yes_price=float(yes_price),
                        no_price=no_price,
                        p_yes_imp=round(p_yes_imp, 4),
                        p_no_imp=round(p_no_imp, 4) if p_no_imp is not None else None,
                        yes_fair_prob=round(p_yes_fair, 4),
                        no_fair_prob=round(p_no_fair, 4),
                    )
                )
                fair_probs_for_consensus.append((p_yes_fair, p_no_fair))

            except (ValueError, ZeroDivisionError):
                continue

    consensus: Optional[Consensus] = None
    if fair_probs_for_consensus:
        consensus_probs = calculate_consensus_mean(fair_probs_for_consensus)
        if consensus_probs:
            yes_fair_consensus = round(consensus_probs[0], 4)
            no_fair_consensus = round(consensus_probs[1], 4)
            consensus = Consensus(
                method="mean",
                p_over_fair=yes_fair_consensus,
                p_under_fair=no_fair_consensus,
                p_yes_fair=yes_fair_consensus,
                p_no_fair=no_fair_consensus,
            )

    if results:
        message = None
    elif rows_dropped_due_to_prior > 0:
        message = (
            f"Single-leg Yes posted by {rows_dropped_due_to_prior} bookmaker(s), "
            "but the league-average vig prior could not be safely applied; "
            "fair probability withheld (not fabricated)."
        )
    else:
        message = "No props data for this player at the selected bookmakers"

    return NoVigResponse(
        event_id=body.event_id,
        player_name=matched_player,
        market=body.market,
        results=results,
        consensus=consensus,
        message=message,
        **_snapshot_metadata(snapshot),
    )


@router.get(
    "/events",
    response_model=EventsResponse,
    summary="Get WNBA games list",
    description="Get WNBA games list for a specified date",
)
async def get_events(
    date: Optional[str] = Query(
        default=None,
        description="Query date (YYYY-MM-DD), defaults to today",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    ),
    regions: str = Query(default="us", description="Region code (us, uk, eu, au)"),
    tz_offset: Optional[int] = Query(
        default=None,
        description=(
            "Timezone offset (minutes); e.g. UTC-6 send -360, UTC+8 send 480. "
            "Filters games to the user's local date."
        ),
    ),
) -> EventsResponse:
    """
    Retrieve WNBA games for ``date`` in the user's local timezone.

    Mirrors GET /api/nba/events — same UTC↔local transform, same cache
    shape (namespaced by ``league=wnba`` via
    ``CacheService.build_events_key``). Reuses ``NBAEvent`` /
    ``EventsResponse`` schemas which are sport-agnostic by content
    (``sport_key`` discriminates).
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    offset_minutes = tz_offset if tz_offset is not None else 0

    # League-namespaced cache key — see CacheService.build_events_key league
    # param. Without this, WNBA + NBA event-list caches would collide in Redis.
    cache_key = (
        f"{CacheService.build_events_key(date, regions, league='wnba')}"
        f":tz{offset_minutes}"
    )
    cached_data = await cache_service.get(cache_key)
    if cached_data:
        return EventsResponse(**cached_data)

    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        local_start = datetime.combine(date_obj.date(), datetime.min.time())
        utc_start = local_start - timedelta(minutes=offset_minutes)
        local_end = datetime.combine(date_obj.date(), time(23, 59, 59))
        utc_end = local_end - timedelta(minutes=offset_minutes)

        # ±1h expansion catches boundary games (mirrors NBA path).
        date_from = utc_start - timedelta(hours=1)
        date_to = utc_end + timedelta(hours=1)

        raw_events = await odds_provider.get_events(
            sport=WNBA_SPORT_KEY,
            regions=regions,
            date_from=date_from,
            date_to=date_to,
        )

        events = []
        for raw_event in raw_events:
            commence_time_str = raw_event.get("commence_time", "")
            if commence_time_str:
                try:
                    commence_utc = datetime.fromisoformat(
                        commence_time_str.replace("Z", "+00:00")
                    )
                    commence_local = commence_utc + timedelta(minutes=offset_minutes)
                    commence_local_date = commence_local.strftime("%Y-%m-%d")
                    if commence_local_date != date:
                        continue
                except ValueError:
                    pass

            events.append(
                NBAEvent(
                    event_id=raw_event.get("id", ""),
                    sport_key=raw_event.get("sport_key", WNBA_SPORT_KEY),
                    home_team=raw_event.get("home_team", ""),
                    away_team=raw_event.get("away_team", ""),
                    commence_time=commence_time_str,
                )
            )

        response = EventsResponse(date=date, events=events)

        await cache_service.set(
            cache_key,
            response.model_dump(mode="json"),
            ttl=settings.cache_ttl_events,
        )
        return response

    except OddsAPIError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.post(
    "/props/no-vig",
    response_model=NoVigResponse,
    summary="Calculate no-vig probabilities (WNBA)",
    description="Query a specific WNBA player prop and calculate no-vig probabilities",
)
@limiter.limit(settings.rate_limit_props)
async def calculate_no_vig(request: Request, body: NoVigRequest) -> NoVigResponse:
    """
    Calculate no-vig probability for a WNBA player prop.

    Mirrors POST /api/nba/props/no-vig. Dispatches on ``body.market``:

    - Over/Under markets (8 hard-supported per SPO-31 Phase 0 + 3 currently
      empty markets) → standard two-leg devig.
    - ``player_double_double`` (binary) → ``_build_binary_no_vig_response``.

    For markets Phase 0 classified as ``schema-valid+empty``
    (``player_steals`` / ``player_blocks`` / ``player_turnovers``), the
    gateway fetches the empty bookmakers array and this handler returns an
    empty ``results=[]`` with a message — same UX as NBA's FTM/FGM
    Tier-B path (SPO-26). No crash, no fabricated rows.
    """
    try:
        snapshot = await odds_gateway.get_market_snapshot(
            sport=WNBA_SPORT_KEY,
            event_id=body.event_id,
            regions=body.regions,
            markets=body.market,
            odds_format=body.odds_format,
            bookmakers=body.bookmakers,
            priority="interactive",
        )
        bookmakers_data = snapshot.data.get("bookmakers", [])
        all_player_names = _collect_player_names(bookmakers_data, body.market)

        matched_player = find_player(body.player_name, all_player_names)

        if not matched_player:
            suggestions = suggest_player_names(
                body.player_name, all_player_names, limit=5, threshold=70
            )
            if suggestions:
                hint = ", ".join(f"{name} ({score})" for name, score in suggestions)
                message = (
                    f"Player '{body.player_name}' not found. Closest names: {hint}"
                )
            else:
                message = (
                    f"Player '{body.player_name}' not found. "
                    f"Available players: {all_player_names[:10]}"
                )
            return NoVigResponse(
                event_id=body.event_id,
                player_name=body.player_name,
                market=body.market,
                results=[],
                consensus=None,
                message=message,
                **_snapshot_metadata(snapshot),
            )

        # DD-binary dispatch — same contract as NBA route (SPO-26).
        if body.market in BINARY_MARKET_KEYS:
            return _build_binary_no_vig_response(
                body=body,
                snapshot=snapshot,
                bookmakers_data=bookmakers_data,
                matched_player=matched_player,
            )

        results: List[BookmakerResult] = []
        fair_probs_for_consensus = []

        for bookmaker in bookmakers_data:
            bookmaker_key = bookmaker.get("key", "unknown")

            for market in bookmaker.get("markets", []):
                if market.get("key") != body.market:
                    continue

                over_outcome = None
                under_outcome = None
                line = None

                for outcome in market.get("outcomes", []):
                    if outcome.get("description") != matched_player:
                        continue
                    outcome_name = (outcome.get("name") or "").lower()
                    if outcome_name == "over":
                        over_outcome = outcome
                        line = outcome.get("point")
                    elif outcome_name == "under":
                        under_outcome = outcome
                        if line is None:
                            line = outcome.get("point")

                if over_outcome is None or under_outcome is None or line is None:
                    continue

                over_odds = over_outcome.get("price", 0)
                under_odds = under_outcome.get("price", 0)
                if over_odds == 0 or under_odds == 0:
                    continue

                try:
                    p_over_imp = american_to_prob(over_odds)
                    p_under_imp = american_to_prob(under_odds)
                    vig = calculate_vig(p_over_imp, p_under_imp)
                    p_over_fair, p_under_fair = devig(p_over_imp, p_under_imp)

                    results.append(
                        BookmakerResult(
                            bookmaker=bookmaker_key,
                            line=line,
                            over_odds=over_odds,
                            under_odds=under_odds,
                            p_over_imp=round(p_over_imp, 4),
                            p_under_imp=round(p_under_imp, 4),
                            vig=round(vig, 4),
                            p_over_fair=round(p_over_fair, 4),
                            p_under_fair=round(p_under_fair, 4),
                            fetched_at=snapshot.fetched_at,
                        )
                    )
                    fair_probs_for_consensus.append((p_over_fair, p_under_fair))
                except (ValueError, ZeroDivisionError):
                    continue

        consensus = None
        if fair_probs_for_consensus:
            consensus_probs = calculate_consensus_mean(fair_probs_for_consensus)
            if consensus_probs:
                consensus = Consensus(
                    method="mean",
                    p_over_fair=round(consensus_probs[0], 4),
                    p_under_fair=round(consensus_probs[1], 4),
                )

        return NoVigResponse(
            event_id=body.event_id,
            player_name=matched_player,
            market=body.market,
            results=results,
            consensus=consensus,
            message=None
            if results
            else "No props data for this player at the selected bookmakers",
            **_snapshot_metadata(snapshot),
        )

    except OddsAPIError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get(
    "/players/suggest",
    response_model=PlayerSuggestResponse,
    summary="WNBA player name suggestion",
    description="Get available WNBA player names for a specific game (autocomplete)",
)
async def suggest_players(
    event_id: str = Query(..., description="Game ID"),
    q: str = Query(default="", description="Search keyword (optional)"),
    market: str = Query(default="player_points", description="Market type"),
) -> PlayerSuggestResponse:
    """
    Autocomplete suggestions for a WNBA event's player list, derived from
    the live odds snapshot (NOT the CSV roster).

    Only players who actually have a prop posted for this event surface —
    same UX as NBA. For full-roster autocomplete (any player in WNBA
    history regardless of whether they're playing tonight), use
    ``GET /api/wnba/csv/players`` (Phase 1 endpoint).
    """
    try:
        snapshot = await odds_gateway.get_market_snapshot(
            sport=WNBA_SPORT_KEY,
            event_id=event_id,
            regions="us",
            markets=market,
            odds_format="american",
            priority="interactive",
        )
        all_players = _collect_player_names(
            snapshot.data.get("bookmakers", []), market
        )
    except OddsAPIError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=str(e))

    if q:
        q_lower = q.lower()
        all_players = [p for p in all_players if q_lower in p.lower()]

    return PlayerSuggestResponse(
        players=all_players,
        **_snapshot_metadata(snapshot),
    )
