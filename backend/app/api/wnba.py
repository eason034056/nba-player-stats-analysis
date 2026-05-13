"""
wnba.py - WNBA related API endpoints (Phase 2, SPO-33)

Sibling of `backend/app/api/nba.py`. Phase 2 adds the odds + no-vig surface
on top of any Phase 1 CSV/history endpoints (SPO-32) that share this file.

Endpoints in THIS file (SPO-33 — Phase 2):
1. GET  /api/wnba/events             — WNBA events for a date
2. POST /api/wnba/props/no-vig       — no-vig probability calc (Over/Under + DD-binary)
3. GET  /api/wnba/players/suggest    — autocomplete from a live event's odds snapshot

💡 Design: this route reuses the **same** parameterized services as NBA —
`odds_gateway`, `odds_provider`, `BINARY_MARKET_KEYS`, the `prob.*` math, the
`normalize.*` fuzzy-match helpers. The only difference vs nba.py is the
hardcoded `WNBA_SPORT_KEY`. Per CLAUDE.md § External API Wrappers:
- Curl-evidence for the WNBA market support set lives in
  `docs/research/wnba-rollout/odds_api_wnba_markets.md` (SPO-31 Phase 0).
- The 9 hard-supported markets all share NBA's Over/Under shape (so the
  same parser works 1:1); `player_double_double` uses the DD-binary path.
- 3 markets (`player_steals`, `player_blocks`, `player_turnovers`) returned
  `schema-valid+empty` in Phase 0 — the existing empty-bookmakers UX from
  SPO-26 handles them without code change.

⚠ Anti-hallucination: do NOT add a market key here that wasn't probed in
Phase 0's research doc. The Odds API silently returns empty `bookmakers=[]`
for unknown keys, so a typo'd market reads as "no lines today" rather than
an error.

🔗 Conflict note (Forge → reviewer): if this file ALSO contains Phase 1
CSV endpoints from SPO-32 by the time you read this, that's expected — the
two phases share the same router/prefix. Both append to the same FastAPI
router instance.
"""

from datetime import datetime, time, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.middleware.rate_limit import limiter
from app.models.schemas import (
    BookmakerResult,
    Consensus,
    EventsResponse,
    NBAEvent,
    NoVigRequest,
    NoVigResponse,
    PlayerSuggestResponse,
)
from app.services.cache import CacheService, cache_service
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


# The Odds API sport key for WNBA — proved live by Phase 0 (SPO-31).
# Centralized as a module constant so a future "league enum" refactor only
# touches one line per route file.
WNBA_SPORT_KEY = "basketball_wnba"

# Same sentinel as nba.py — the binary-market line has no real threshold;
# 0.5 is the convention odds_snapshot_service._parse_binary_market writes
# to the DB. Mirrored here so /props/no-vig responses for DD agree with
# any future snapshot-stored rows.
_BINARY_LINE_SENTINEL = 0.5


router = APIRouter(
    prefix="/api/wnba",
    tags=["wnba"],
)


# ==================== Internal helpers (mirror nba.py) ========================
# These mirror the nba.py helpers verbatim. Duplication is intentional:
# - The NBA route is explicitly out of SPO-33 scope ("existing NBA path
#   unchanged"), so refactoring shared helpers into a service module would
#   force a touch on nba.py that the issue spec forbids.
# - Three similar lines is better than a premature abstraction (CLAUDE.md).
# - When a third league is added, factor these out into a `league_route_helpers`
#   service module at that point.


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

    Mirrors `nba.py._build_binary_no_vig_response`. Uses `single_leg_devig`
    when only the Yes leg is posted (most common — see Phase 0 research §3.2.3
    where only `Yes` legs were observed on the Storm @ Tempo snapshot). If
    `single_leg_devig` fails (vig prior cannot be honestly applied), the row
    is dropped rather than fabricating a number — anti-hallucination rule
    from decision_20260502_market-key-feasibility §4.
    """
    results: List[BookmakerResult] = []
    fair_probs_for_consensus: list[tuple[float, float]] = []
    dropped_books: list[str] = []

    for bookmaker in bookmakers_data:
        bookmaker_key = bookmaker.get("key", "unknown")

        for market in bookmaker.get("markets", []):
            if market.get("key") != body.market:
                continue

            yes_outcome = None
            no_outcome = None
            for outcome in market.get("outcomes", []):
                if outcome.get("description") != matched_player:
                    continue
                name = (outcome.get("name") or "").lower()
                if name == "yes":
                    yes_outcome = outcome
                elif name == "no":
                    no_outcome = outcome

            if yes_outcome is None and no_outcome is None:
                continue

            yes_price = yes_outcome.get("price") if yes_outcome else None
            no_price = no_outcome.get("price") if no_outcome else None

            try:
                if yes_price is not None and no_price is not None:
                    # Two-leg path — same shape as Over/Under but Yes/No.
                    p_yes_imp = american_to_prob(yes_price)
                    p_no_imp = american_to_prob(no_price)
                    vig = calculate_vig(p_yes_imp, p_no_imp)
                    p_yes_fair, p_no_fair = devig(p_yes_imp, p_no_imp)
                elif yes_price is not None:
                    # Single-leg Yes path — vig assumed via DEFAULT_BINARY_VIG.
                    # `single_leg_devig` returns None when the prior can't be
                    # honestly applied; surface that as a drop, not a fake row.
                    p_yes_imp = american_to_prob(yes_price)
                    devigged = single_leg_devig(p_yes_imp, DEFAULT_BINARY_VIG)
                    if devigged is None:
                        dropped_books.append(bookmaker_key)
                        continue
                    p_yes_fair = devigged
                    p_no_fair = 1.0 - p_yes_fair
                    vig = DEFAULT_BINARY_VIG
                    p_no_imp = 1.0 - p_yes_imp
                else:
                    # Only `No` posted — also single-leg.
                    p_no_imp = american_to_prob(no_price)
                    devigged = single_leg_devig(p_no_imp, DEFAULT_BINARY_VIG)
                    if devigged is None:
                        dropped_books.append(bookmaker_key)
                        continue
                    p_no_fair = devigged
                    p_yes_fair = 1.0 - p_no_fair
                    vig = DEFAULT_BINARY_VIG
                    p_yes_imp = 1.0 - p_no_imp
            except (ValueError, ZeroDivisionError):
                dropped_books.append(bookmaker_key)
                continue

            result = BookmakerResult(
                bookmaker=bookmaker_key,
                line=_BINARY_LINE_SENTINEL,
                over_odds=yes_price if yes_price is not None else 0,
                under_odds=no_price if no_price is not None else 0,
                p_over_imp=round(p_yes_imp, 4),
                p_under_imp=round(p_no_imp, 4),
                vig=round(vig, 4),
                p_over_fair=round(p_yes_fair, 4),
                p_under_fair=round(p_no_fair, 4),
                fetched_at=snapshot.fetched_at,
                yes_price=yes_price,
                no_price=no_price,
                p_yes_imp=round(p_yes_imp, 4),
                p_no_imp=round(p_no_imp, 4),
                yes_fair_prob=round(p_yes_fair, 4),
                no_fair_prob=round(p_no_fair, 4),
            )
            results.append(result)
            fair_probs_for_consensus.append((p_yes_fair, p_no_fair))

    consensus = None
    if fair_probs_for_consensus:
        consensus_probs = calculate_consensus_mean(fair_probs_for_consensus)
        if consensus_probs:
            consensus = Consensus(
                method="mean",
                p_over_fair=round(consensus_probs[0], 4),
                p_under_fair=round(consensus_probs[1], 4),
            )

    message = None
    if not results and dropped_books:
        message = (
            f"Binary market quotes dropped for {len(dropped_books)} bookmaker(s) "
            "— single-leg prior could not be honestly applied."
        )
    elif not results:
        message = "No DD lines for this player at the selected bookmakers"

    return NoVigResponse(
        event_id=body.event_id,
        player_name=matched_player,
        market=body.market,
        results=results,
        consensus=consensus,
        message=message,
        **_snapshot_metadata(snapshot),
    )


# ==================== Endpoints ===============================================


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
    regions: str = Query(
        default="us",
        description="Region code (us, uk, eu, au)",
    ),
    tz_offset: Optional[int] = Query(
        default=None,
        description=(
            "Timezone offset (minutes); e.g. UTC-6 send -360, UTC+8 send 480. "
            "Used to filter games to the user's local date."
        ),
    ),
) -> EventsResponse:
    """
    Retrieve WNBA games for `date` in the user's local timezone.

    Mirrors `GET /api/nba/events` — same date-window logic, same UTC↔local
    transform, same cache shape (namespaced by `league=wnba` via
    `CacheService.build_events_key`).

    Returns:
        EventsResponse with one or more `NBAEvent` rows (schema is sport-agnostic
        despite the name — `sport_key` discriminates).
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    offset_minutes = tz_offset if tz_offset is not None else 0

    # League-namespaced cache key so NBA + WNBA event lists for the same
    # date+region don't collide in Redis.
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

        # ±1h expansion to catch boundary games (mirrors NBA path).
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

    Mirrors `POST /api/nba/props/no-vig`. Dispatches on `body.market`:
    - Over/Under markets (the 8 hard-supported ones in Phase 0 + 3 currently
      empty markets) → standard two-leg devig.
    - `player_double_double` (binary) → `_build_binary_no_vig_response`.

    For markets that returned `schema-valid+empty` in Phase 0
    (`player_steals` / `player_blocks` / `player_turnovers`), the gateway
    fetches the empty bookmakers array and this handler returns an empty
    `results=[]` with a message — same UX as NBA's FTM/FGM Tier-B path
    (SPO-26). No crash, no fabricated rows.
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
    the live odds snapshot (NOT the CSV roster). This means only players
    who actually have a prop posted for this event surface — same UX as
    NBA. For full-roster autocomplete (any player in WNBA history,
    regardless of whether they're playing tonight), use the SPO-32
    Phase 1 endpoint `GET /api/wnba/csv/players`.
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
