"""
nba.py - NBA related API endpoints

Includes:
1. Game List API (GET /api/nba/events)
2. One game from that list (GET /api/nba/events/{event_id})
3. No-Vig Probability Calculation API (POST /api/nba/props/no-vig)
4. Player Suggestions API (GET /api/nba/players/suggest)

This is the core functional module of the application.
"""

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from datetime import datetime, timezone, timedelta, time
from typing import List, Optional
from zoneinfo import ZoneInfo

from app.middleware.rate_limit import limiter
from app.models.schemas import (
    EventsResponse,
    NBAEvent,
    NoVigRequest,
    NoVigResponse,
    BookmakerResult,
    Consensus,
    PlayerSuggestResponse,
    PlayerSuggestion,
    CSVPlayersResponse,
    PlayerHistoryResponse,
    PlayerDDHistoryResponse,
    HistogramBin,
    GameLog,
    TeammateContext,
    BulkPropsResponse,
)
from app.services.bulk_props import (
    BulkPropsQueryFailed,
    BulkPropsStoreUnavailable,
    UnknownMarkets,
    event_id_is_well_formed,
    get_event_bulk_props,
    parse_market_filter,
)
from app.services.daily_analysis import attach_top_reads, load_stored_top_reads
from app.services.odds_theoddsapi import odds_provider
from app.services.odds_provider import OddsAPIError
from app.services.cache import cache_service, CacheService
from app.services.odds_gateway import odds_gateway, MarketSnapshotResult
from app.services.odds_snapshot_service import BINARY_MARKET_KEYS
from app.services.game_log_hygiene import coalesce_game_type
from app.services.event_fields import enrich_nba_event
from app.services.lineup_service import lineup_service
from app.services.prob import (
    american_to_prob,
    posted_american_odds,
    calculate_vig,
    devig,
    calculate_consensus_mean,
    single_leg_devig,
    DEFAULT_BINARY_VIG,
)
from app.services.normalize import extract_player_names, find_player, suggest_players as suggest_player_names
# CONTINUOUS_METRIC_EXTRACTORS is the canonical 11-key continuous-metric
# dispatch table (SPO-16). Importing it directly keeps the API route's
# valid_metrics in lockstep with the services layer — adding a new metric
# to the extractor table automatically flows through to the route, removing
# a place to forget. Binary metrics (currently `dd`) flow through their own
# `/player-dd-history` endpoint, not this route.
from app.services.csv_player_history import csv_player_service, CONTINUOUS_METRIC_EXTRACTORS
from app.settings import settings


# Binary-market sentinel for line value (no real bookmaker threshold for
# Yes/No bets). Mirrors `odds_snapshot_service._parse_binary_market`'s
# convention so /props/no-vig responses agree with snapshot-stored rows.
_BINARY_LINE_SENTINEL = 0.5

# Initialize router
router = APIRouter(
    prefix="/api/nba",
    tags=["nba"]
)

logger = logging.getLogger(__name__)


async def _events_with_top_reads(
    response: EventsResponse,
    offset_minutes: int,
) -> EventsResponse:
    """Attach the best stored NBA pick to each event.

    Reads the daily-picks cache for this date and timezone. It does not
    run analysis and does not call the Odds API. A join failure leaves
    every top_read null so the event list still returns.
    """
    try:
        reads = await load_stored_top_reads(response.date, offset_minutes)
    except Exception:
        logger.exception("NBA top_read join failed for %s", response.date)
        return response
    return attach_top_reads(response, reads)


async def _with_event_fields(response: EventsResponse) -> EventsResponse:
    """Attach the ET clock and the lineup confirmation.

    Lineups are read from cache only. A scrape belongs on
    ``GET /api/nba/lineups``, not on the events list.
    """
    try:
        lineups = await lineup_service.peek_lineups(response.date)
    except Exception as exc:
        logger.warning(
            "NBA lineup peek failed for %s",
            response.date,
            exc_info=exc,
        )
        lineups = {}
    return response.model_copy(
        update={
            "events": [
                enrich_nba_event(event, lineups) for event in response.events
            ]
        }
    )


async def _with_reads_and_event_fields(
    response: EventsResponse,
    offset_minutes: int,
) -> EventsResponse:
    """Join ``top_read``, then the ET clock and lineup confirmation.

    ``_events_with_top_reads`` copies each event and sets only
    ``top_read``. ``_with_event_fields`` copies that result and sets
    only the clock and ``lineup_status``. The second copy keeps
    ``top_read``.
    """
    with_reads = await _events_with_top_reads(response, offset_minutes)
    return await _with_event_fields(with_reads)


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

    Mirrors the Over/Under flow's per-bookmaker loop, but:
      1. Outcomes are matched by ``name in {"yes", "no"}`` (not over/under).
      2. There is no `point` field — the response uses the
         `_BINARY_LINE_SENTINEL` (0.5) and consumers must dispatch on
         `body.market`, not the line value.
      3. When only the Yes leg is posted, vig is approximated via
         `single_leg_devig(p_yes_imp, DEFAULT_BINARY_VIG)`. If the prior
         cannot be safely applied (extreme prices), THIS ROW IS NOT
         EMITTED — the route does not surface a fabricated fair-prob
         (anti-hallucination guard, decision §4 step 3). The aggregate
         message names the omission so callers know data was withheld.

    Both new explicit binary fields (`yes_price`, `p_yes_imp`,
    `yes_fair_prob`, etc.) AND the legacy over/under fields are populated
    on each emitted row. The legacy fields use the convention
    "over = Yes leg, under = posted No leg". A missing No price stays
    None on `under_odds`, `p_under_imp`, `no_price`, and `p_no_imp`.
    It is not copied from Yes, and `p_under_imp` is not `1 - p_yes_imp`.
    `p_under_fair` / `no_fair_prob` remain the complement of the
    de-vigged Yes fair, which is a model output. `line_is_synthetic`
    is True and `market_kind` is "binary" because `line` is the 0.5
    sentinel, not a posted total.
    """
    results: List[BookmakerResult] = []
    fair_probs_for_consensus: List[tuple] = []
    prior_book_count = 0
    rows_dropped_due_to_prior = 0

    for bookmaker in bookmakers_data:
        bookmaker_key = bookmaker.get("key", "unknown")

        for market in bookmaker.get("markets", []):
            if market.get("key") != body.market:
                continue

            # Collect Yes/No outcomes for the matched player.
            yes_outcome: Optional[dict] = None
            no_outcome: Optional[dict] = None
            for outcome in market.get("outcomes", []):
                if outcome.get("description") != matched_player:
                    continue
                outcome_name = outcome.get("name", "").lower()
                if outcome_name == "yes":
                    yes_outcome = outcome
                elif outcome_name == "no":
                    no_outcome = outcome

            # Without a Yes price there is nothing to anchor any de-vig
            # calculation on; skip this bookmaker rather than fabricate.
            if yes_outcome is None:
                continue

            yes_price = posted_american_odds(yes_outcome.get("price"))
            if yes_price is None:
                continue
            no_price_raw = (
                posted_american_odds(no_outcome.get("price"))
                if no_outcome is not None
                else None
            )

            try:
                p_yes_imp = american_to_prob(yes_price)
                no_price: Optional[float]
                p_no_imp: Optional[float]

                if no_price_raw is not None:
                    # Both legs posted — derive vig directly from the leg
                    # pair, matching the Over/Under flow's higher-fidelity
                    # path. No prior assumption needed.
                    no_price = float(no_price_raw)
                    p_no_imp = american_to_prob(no_price_raw)
                    vig = calculate_vig(p_yes_imp, p_no_imp)
                    p_yes_fair, p_no_fair = devig(p_yes_imp, p_no_imp)
                    uses_prior = False
                else:
                    # Only Yes posted — apply the league-average prior.
                    # When the prior cannot be safely applied (extreme
                    # prices, see prob.single_leg_devig), DO NOT publish
                    # a fabricated fair-prob — drop the row instead.
                    no_price = None
                    p_no_imp = None
                    p_yes_fair = single_leg_devig(p_yes_imp, DEFAULT_BINARY_VIG)
                    if p_yes_fair is None:
                        rows_dropped_due_to_prior += 1
                        continue
                    # Once Yes fair is computed, No fair is the exact
                    # mathematical complement (probabilities of a binary
                    # outcome must sum to 1) — not a fabrication.
                    p_no_fair = 1.0 - p_yes_fair
                    vig = DEFAULT_BINARY_VIG  # the prior we assumed
                    uses_prior = True

                # Legacy over/under fields encode "over = Yes" and
                # "under = posted No". A book that did not post No leaves
                # under_odds and p_under_imp empty. The fair No probability
                # below is still the complement of the de-vigged Yes fair.
                results.append(
                    BookmakerResult(
                        bookmaker=bookmaker_key,
                        line=_BINARY_LINE_SENTINEL,
                        over_odds=float(yes_price),
                        under_odds=float(no_price) if no_price is not None else None,
                        p_over_imp=round(p_yes_imp, 4),
                        p_under_imp=round(p_no_imp, 4) if p_no_imp is not None else None,
                        vig=round(vig, 4),
                        p_over_fair=round(p_yes_fair, 4),
                        p_under_fair=round(p_no_fair, 4),
                        fetched_at=snapshot.fetched_at,
                        line_is_synthetic=True,
                        market_kind="binary",
                        uses_prior=uses_prior,
                        # Explicit binary mirrors — preferred for new
                        # consumers (e.g. SPO-20 PlayerDDTile).
                        yes_price=float(yes_price),
                        no_price=no_price,
                        p_yes_imp=round(p_yes_imp, 4),
                        p_no_imp=round(p_no_imp, 4) if p_no_imp is not None else None,
                        yes_fair_prob=round(p_yes_fair, 4),
                        no_fair_prob=round(p_no_fair, 4),
                    )
                )
                fair_probs_for_consensus.append((p_yes_fair, p_no_fair))
                if uses_prior:
                    prior_book_count += 1

            except (ValueError, ZeroDivisionError):
                # american_to_prob rejects 0 odds; defensive fallthrough.
                continue

    # Consensus across bookmakers. For binary markets, the legacy
    # p_over_fair/p_under_fair carry Yes/No values; we ALSO populate the
    # explicit p_yes_fair/p_no_fair mirrors.
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
                consensus_uses_prior=prior_book_count > 0,
                consensus_prior_book_count=prior_book_count,
            )

    # Aggregate message: distinguish "no inventory at all" from "inventory
    # existed but the prior could not safely be applied". The latter is the
    # honest equivalent of "yes_fair_prob is null" — we drop the row rather
    # than fabricate, and surface the omission explicitly.
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
    summary="Get NBA games list",
    description="Get NBA games list for a specified date"
)
async def get_events(
    date: Optional[str] = Query(
        default=None,
        description="Query date (YYYY-MM-DD), defaults to today",
        pattern=r"^\d{4}-\d{2}-\d{2}$"
    ),
    regions: str = Query(
        default="us",
        description="Region code (us, uk, eu, au)"
    ),
    tz_offset: Optional[int] = Query(
        default=None,
        description=(
            "Timezone offset in minutes, e.g. UTC-6 send -360, UTC+8 send 480. "
            "Used for filtering local date games. Omitted values use 480, the "
            "same default as GET /api/nba/daily-picks, so the top_read cache key matches."
        ),
    )
) -> EventsResponse:
    """
    Get NBA games list

    GET /api/nba/events?date=YYYY-MM-DD&regions=us

    Flow:
    1. Check Redis cache
    2. If cache hit, return directly
    3. If cache miss, call The Odds API
    4. Store result in cache
    5. Return result

    Args:
        date: Query date (YYYY-MM-DD), defaults to today
        regions: Region code, affects available bookmakers

    Returns:
        EventsResponse: Games list

    Raises:
        HTTPException: API call fails

    Example Response:
        {
            "date": "2026-01-14",
            "events": [
                {
                    "event_id": "abc123",
                    "sport_key": "basketball_nba",
                    "home_team": "Los Angeles Lakers",
                    "away_team": "Golden State Warriors",
                    "commence_time": "2026-01-15T01:00:00Z",
                    "top_read": null
                }
            ]
        }
    """
    # Handle date param: defaults to today UTC. The detail route computes
    # its own local date before calling here. This default stays UTC.
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Omitted tz_offset uses 480 (UTC+8), the same default as
    # GET /api/nba/daily-picks. top_read is loaded with
    # daily_picks:nba:{date}:tz{offset}, so a different default would miss
    # the cache and leave every top_read null. The frontend sends an
    # explicit offset; this default is only for callers who omit it.
    # JavaScript's getTimezoneOffset() returns "UTC - Local" minutes
    # (UTC+8 is -480). Callers should send the normal offset (UTC+8 is 480).
    offset_minutes = tz_offset if tz_offset is not None else 480

    # A string that matches YYYY-MM-DD can still be impossible (month 13).
    # Reject it here, before the cache read and before the broad
    # ``except Exception`` below, so the client gets a plain 422 and the
    # parser message is not copied into the body.
    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date")

    # 1. Check cache (include timezone offset to distinguish different local time requests)
    cache_key = f"{CacheService.build_events_key(date, regions)}:tz{offset_minutes}"
    cached_data = await cache_service.get(cache_key)
    
    if cached_data:
        # Cache hit. top_read is joined after the read so a fresher
        # daily-picks cache is not stuck behind the events TTL. The ET
        # clock and lineup confirmation are applied on that result, so
        # a stored payload from before those fields still comes back
        # filled. The cached body itself stays the Odds API shape.
        return await _with_reads_and_event_fields(
            EventsResponse(**cached_data),
            offset_minutes,
        )
    
    # 2. Cache miss, call external API
    try:
        # Calculate UTC time range for user's local date
        # Example: If user is UTC-6 and selects "2026-01-17"
        # Local 2026-01-17 00:00:00 = UTC 2026-01-17 06:00:00
        # Local 2026-01-17 23:59:59 = UTC 2026-01-18 05:59:59
        # date_obj was parsed above. One calendar day, then the existing
        # ±1h window. No second day and no extra provider call.

        # Local 00:00:00 to UTC
        local_start = datetime.combine(date_obj.date(), datetime.min.time())
        utc_start = local_start - timedelta(minutes=offset_minutes)
        
        # Local 23:59:59 to UTC (avoid datetime.max.time to skip microseconds)
        local_end = datetime.combine(date_obj.date(), time(23, 59, 59))
        utc_end = local_end - timedelta(minutes=offset_minutes)
        
        # Expand search range to cover boundary cases
        date_from = utc_start - timedelta(hours=1)
        date_to = utc_end + timedelta(hours=1)
        
        raw_events = await odds_provider.get_events(
            sport="basketball_nba",
            regions=regions,
            date_from=date_from,
            date_to=date_to
        )
        
        # 3. Transform and filter data by date
        # Filter: return only games whose commence time falls within local date
        events = []
        for raw_event in raw_events:
            commence_time_str = raw_event.get("commence_time", "")
            
            if commence_time_str:
                # Parse UTC time (e.g. 2026-01-17T00:10:00Z)
                try:
                    commence_utc = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
                    # Convert to local time
                    commence_local = commence_utc + timedelta(minutes=offset_minutes)
                    # Get local date
                    commence_local_date = commence_local.strftime("%Y-%m-%d")
                    
                    # Only return games where local date matches request
                    if commence_local_date != date:
                        continue
                except ValueError:
                    # Couldn't parse time, skip filter
                    pass
            
            events.append(NBAEvent(
                event_id=raw_event.get("id", ""),
                sport_key=raw_event.get("sport_key", "basketball_nba"),
                home_team=raw_event.get("home_team", ""),
                away_team=raw_event.get("away_team", ""),
                commence_time=commence_time_str
            ))
        
        # 4. Build response
        response = EventsResponse(
            date=date,
            events=events
        )
        
        # 5. Store the event list. top_read is joined on the way out and
        # is not part of this payload's freshness: the next read joins
        # whatever daily picks are stored for this date and offset.
        await cache_service.set(
            cache_key,
            response.model_dump(mode='json'),
            ttl=settings.cache_ttl_events
        )

        return await _with_reads_and_event_fields(response, offset_minutes)
        
    except OddsAPIError as e:
        raise HTTPException(
            status_code=e.status_code or 500,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal error: {str(e)}"
        )


@router.get(
    "/events/{event_id}",
    response_model=NBAEvent,
    summary="Get one NBA game",
    description="""
    One game from the same list as GET /api/nba/events.

    The handler calls that list. A Redis hit for the same date, regions,
    and tz_offset returns the stored list. A miss uses the same events
    request the list uses, then stores that list. This route does not
    call the per-event odds endpoint or the odds gateway.

    Pass the date and tz_offset you loaded this event with. Those two
    values are what the list stored under, so the cache key matches.
    If date is omitted, the default is the caller's local date: UTC now
    plus tz_offset minutes. Omitted tz_offset is 480. regions defaults
    to us. The list route still treats an omitted date as today UTC.

    A malformed event_id is HTTP 404 and the list is not read. The id
    rule is the same as GET /api/nba/events/{event_id}/props: 1–128
    characters from [A-Za-z0-9_-], starting with a letter or digit. A
    well-formed id that is not on that date's list is HTTP 404.

    The body is one NBAEvent, the same model WNBA's event list uses,
    with the fields GET /api/nba/events already adds for an NBA event
    (commence_time_et, display_tz, lineup_status, top_read).
    """,
)
@limiter.limit(settings.rate_limit_props)
async def get_event(
    request: Request,
    event_id: str,
    date: Optional[str] = Query(
        default=None,
        description=(
            "Local date (YYYY-MM-DD). Pass the date and tz_offset you "
            "loaded this event with. Omitted date is the caller's local "
            "date from tz_offset."
        ),
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    ),
    regions: str = Query(
        default="us",
        description="Region code (us, uk, eu, au). Same as GET /api/nba/events.",
    ),
    tz_offset: Optional[int] = Query(
        default=None,
        description=(
            "Timezone offset in minutes. Omitted values use 480, the same "
            "default as GET /api/nba/events."
        ),
    ),
) -> NBAEvent:
    """One NBA event from the events list.

    ``get_event`` is the HTTP handler. The name is the singular of
    ``get_events``: one game, not the day's list. Call it as
    ``GET /api/nba/events/{event_id}``. Pass the same ``date``,
    ``regions``, and ``tz_offset`` the event was loaded with, so both
    share one cache key. When ``date`` is omitted, the default is the
    caller's local date from ``tz_offset`` (UTC now plus that many
    minutes; omitted offset is 480). The list route's omitted date
    stays today UTC.

    The handler checks the id with ``event_id_is_well_formed``, then
    calls ``get_events`` once. That function reads Redis and, on a miss,
    ``odds_provider.get_events`` for that one local day. It does not
    call ``odds_gateway``, and it does not try the next day.

    Args:
        request: Incoming request. The slowapi limiter reads it. Same
            limit as ``GET /api/nba/events/{event_id}/props``
            (``settings.rate_limit_props``).
        event_id: Path id. Malformed ids and ids missing from that
            date's list are 404.
        date: Local date YYYY-MM-DD. Pass the date you loaded this
            event with. Omitted value is the caller's local date from
            tz_offset.
        regions: Region code. Default ``us``.
        tz_offset: Minutes east of UTC. Pass the offset you loaded this
            event with. Omitted uses 480.

    Returns:
        The ``NBAEvent`` for this id on that date's list.

    Raises:
        HTTPException: 404 when the id is malformed or not on the list.
            422 ``Invalid date`` when the calendar date is impossible.
            Odds API errors from the list path pass through.
    """
    if not event_id_is_well_formed(event_id):
        raise HTTPException(status_code=404, detail="Malformed event_id")

    # Detail-only. get_events still treats an omitted date as today UTC.
    # One local date, then one list read. No next-day fallback.
    if date is None:
        offset_minutes = tz_offset if tz_offset is not None else 480
        date = (
            datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
        ).strftime("%Y-%m-%d")

    listing = await get_events(date=date, regions=regions, tz_offset=tz_offset)
    for event in listing.events:
        if event.event_id == event_id:
            return event
    raise HTTPException(status_code=404, detail="Event not found")


@router.get(
    "/events/{event_id}/props",
    response_model=BulkPropsResponse,
    summary="Stored lines for every player in one NBA game",
    description="""
    Read the latest `odds_line_snapshots` capture for this event.

    The capture is written by the odds snapshot scheduler. This route does
    not call The Odds API, including when no capture is stored.

    A well-formed `event_id` with no snapshot is HTTP 200: `markets` is
    empty, and `snapshot_at` and `data_age_seconds` are null. A malformed
    `event_id` (empty, or anything other than 1–128 characters from
    `[A-Za-z0-9_-]` starting with a letter or digit) is HTTP 404 and is
    not looked up.

    `markets` is an optional comma-separated list of snapshot market keys.
    An unknown key is HTTP 400. Omit it to return every market in the
    capture. `player` is an optional exact name, case-insensitive. A
    filter that matches nobody still returns the snapshot timestamp when
    a capture exists.

    `source` is always `"snapshot"`. Each bookmaker votes once. The
    player's `line` is the modal consensus of those votes.
    """,
)
@limiter.limit(settings.rate_limit_props)
async def get_event_props(
    request: Request,
    event_id: str,
    markets: Optional[str] = Query(
        default=None,
        description=(
            "Comma-separated snapshot market keys. "
            "Omit to return every market in the latest capture"
        ),
    ),
    player: Optional[str] = Query(
        default=None,
        description="Exact player name, case-insensitive. Omit to return every player",
    ),
) -> BulkPropsResponse:
    """
    Stored props for one NBA event.

    ``get_event_props`` is the HTTP handler. "Event" is the Odds API game
    id. "Props" is every player line in that game. Call it as
    ``GET /api/nba/events/{event_id}/props``. Optional query ``markets``
    (comma-separated keys) and ``player`` (exact name).

    The handler checks the id and the market list, then calls
    ``get_event_bulk_props``. That function reads Postgres (and a 60s
    Redis copy of the assembled JSON). It does not call the Odds API.

    Args:
        request: Incoming request. The slowapi limiter reads it. Same
            limit as ``POST /api/nba/props/no-vig``
            (``settings.rate_limit_props``).
        event_id: Path id. Malformed ids are 404.
        markets: Comma-separated market filter, or omitted.
        player: Exact player name, or omitted.

    Returns:
        BulkPropsResponse. Empty markets and a null snapshot time when
        nothing is stored.

    Raises:
        HTTPException: 404 malformed id, 400 unknown market, 503 database
            disconnected, 500 snapshot query failed.
    """
    if not event_id_is_well_formed(event_id):
        raise HTTPException(status_code=404, detail="Malformed event_id")

    try:
        market_filter = parse_market_filter(markets)
    except UnknownMarkets as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        return await get_event_bulk_props(
            event_id,
            markets=market_filter,
            player=player,
        )
    except BulkPropsStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BulkPropsQueryFailed as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/props/no-vig",
    response_model=NoVigResponse,
    summary="Calculate no-vig probabilities",
    description="Query specific player props and calculate no-vig probabilities"
)
@limiter.limit(settings.rate_limit_props)
async def calculate_no_vig(request: Request, body: NoVigRequest) -> NoVigResponse:
    """
    Calculate no-vig probability for player props

    POST /api/nba/props/no-vig

    This is a core feature of the application!

    Flow:
    1. Check cache (using event_id + market + regions + bookmakers as key)
    2. If cache miss, call The Odds API for props data
    3. Search for specified player in outcomes (fuzzy matching)
    4. For each bookmaker:
       a. Get line (threshold), over_odds, under_odds
       b. Calculate implied probability
       c. Calculate vig
       d. Calculate fair probability (no-vig)
    5. Calculate market consensus (average of all bookmakers)
    6. Store in cache and return

    Args:
        request: NoVigRequest containing:
            - event_id: Game ID
            - player_name: Player name
            - market: Market type (default player_points)
            - regions: Region code
            - bookmakers: Specific bookmakers (optional)
            - odds_format: Odds format

    Returns:
        NoVigResponse: Contains results from each bookmaker and market consensus

    Example Request:
        {
            "event_id": "abc123",
            "player_name": "Stephen Curry",
            "market": "player_points",
            "regions": "us",
            "bookmakers": ["draftkings", "fanduel"]
        }
    """
    try:
        snapshot = await odds_gateway.get_market_snapshot(
            sport="basketball_nba",
            event_id=body.event_id,
            regions=body.regions,
            markets=body.market,
            odds_format=body.odds_format,
            bookmakers=body.bookmakers,
            priority="interactive",
        )
        bookmakers_data = snapshot.data.get("bookmakers", [])
        all_player_names = _collect_player_names(bookmakers_data, body.market)

        # 3. Match player name
        matched_player = find_player(
            body.player_name,
            all_player_names
        )

        if not matched_player:
            suggestions = suggest_player_names(body.player_name, all_player_names, limit=5, threshold=70)
            if suggestions:
                hint = ", ".join(f"{name} ({score})" for name, score in suggestions)
                message = f"Player '{body.player_name}' not found. Closest names: {hint}"
            else:
                message = f"Player '{body.player_name}' not found. Available players: {all_player_names[:10]}"
            return NoVigResponse(
                event_id=body.event_id,
                player_name=body.player_name,
                market=body.market,
                results=[],
                consensus=None,
                message=message,
                **_snapshot_metadata(snapshot),
            )

        # ⚠ Dispatch on market shape: binary Yes/No markets (e.g.
        # `player_double_double`) have a fundamentally different outcome
        # shape (`name=Yes|No`, no `point` field) and cannot share the
        # Over/Under parsing path below. Force them through the dedicated
        # helper, which handles single-leg-only quotes via
        # `single_leg_devig` and refuses to fabricate fair probabilities
        # when the prior fails (decision_20260502_market-key-feasibility §4).
        if body.market in BINARY_MARKET_KEYS:
            return _build_binary_no_vig_response(
                body=body,
                snapshot=snapshot,
                bookmakers_data=bookmakers_data,
                matched_player=matched_player,
            )

        # 4. Calculate no-vig probabilities for each bookmaker
        results: List[BookmakerResult] = []
        fair_probs_for_consensus = []

        for bookmaker in bookmakers_data:
            bookmaker_key = bookmaker.get("key", "unknown")

            for market in bookmaker.get("markets", []):
                if market.get("key") != body.market:
                    continue

                # Find Over and Under outcomes for player
                over_outcome = None
                under_outcome = None
                line = None

                for outcome in market.get("outcomes", []):
                    if outcome.get("description") == matched_player:
                        outcome_name = outcome.get("name", "").lower()

                        if outcome_name == "over":
                            over_outcome = outcome
                            line = outcome.get("point")
                        elif outcome_name == "under":
                            under_outcome = outcome
                            if line is None:
                                line = outcome.get("point")

                # Require both Over and Under to calculate
                if over_outcome is None or under_outcome is None or line is None:
                    continue

                over_odds = over_outcome.get("price", 0)
                under_odds = under_outcome.get("price", 0)

                if over_odds == 0 or under_odds == 0:
                    continue

                # 5. Calculate probabilities
                try:
                    # Implied probabilities (with vig)
                    p_over_imp = american_to_prob(over_odds)
                    p_under_imp = american_to_prob(under_odds)

                    # Vig (house edge)
                    vig = calculate_vig(p_over_imp, p_under_imp)

                    # No-vig (fair) probabilities
                    p_over_fair, p_under_fair = devig(p_over_imp, p_under_imp)

                    # Build result
                    result = BookmakerResult(
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
                        line_is_synthetic=False,
                        market_kind="over_under",
                        uses_prior=False,
                    )
                    results.append(result)
                    fair_probs_for_consensus.append((p_over_fair, p_under_fair))

                except (ValueError, ZeroDivisionError):
                    # Calculation error, skip this bookmaker
                    continue

        # 6. Calculate market consensus
        consensus = None
        if fair_probs_for_consensus:
            consensus_probs = calculate_consensus_mean(fair_probs_for_consensus)
            if consensus_probs:
                consensus = Consensus(
                    method="mean",
                    p_over_fair=round(consensus_probs[0], 4),
                    p_under_fair=round(consensus_probs[1], 4),
                    consensus_uses_prior=False,
                    consensus_prior_book_count=0,
                )

        # 7. Build response
        return NoVigResponse(
            event_id=body.event_id,
            player_name=matched_player,  # Use the matched name
            market=body.market,
            results=results,
            consensus=consensus,
            message=None if results else "No props data for this player at the selected bookmakers",
            **_snapshot_metadata(snapshot),
        )
        
    except OddsAPIError as e:
        raise HTTPException(
            status_code=e.status_code or 500,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal error: {str(e)}"
        )


@router.get(
    "/players/suggest",
    response_model=PlayerSuggestResponse,
    summary="Player name suggestion",
    description="Get available player names for a specific game (for autocomplete)"
)
async def suggest_players(
    event_id: str = Query(..., description="Game ID"),
    q: str = Query(default="", description="Search keyword (optional)"),
    market: str = Query(default="player_points", description="Market type")
) -> PlayerSuggestResponse:
    """
    Get player name suggestions (for Autocomplete)

    GET /api/nba/players/suggest?event_id=abc123&q=cur

    Flow:
    1. Check cache
    2. If cache miss, call The Odds API for game props
    3. Extract all player names from outcomes
    4. Filter by keyword if given
    5. Store in cache and return

    Args:
        event_id: Game ID
        q: Search keyword (for filtering)
        market: Market type

    Returns:
        PlayerSuggestResponse: List of player names

    Example Response:
        {
            "players": ["Stephen Curry", "Seth Curry", "LeBron James"]
        }
    """
    try:
        snapshot = await odds_gateway.get_market_snapshot(
            sport="basketball_nba",
            event_id=event_id,
            regions="us",
            markets=market,
            odds_format="american",
            priority="interactive",
        )
        all_players = _collect_player_names(snapshot.data.get("bookmakers", []), market)
    except OddsAPIError as e:
        raise HTTPException(
            status_code=e.status_code or 500,
            detail=str(e)
        )
    
    # 5. Filter if keyword is given
    if q:
        q_lower = q.lower()
        all_players = [p for p in all_players if q_lower in p.lower()]
    
    return PlayerSuggestResponse(
        players=all_players,
        suggestions=[
            PlayerSuggestion(
                name=name,
                position=csv_player_service.latest_position(name),
            )
            for name in all_players
        ],
        **_snapshot_metadata(snapshot),
    )


# ==================== CSV Player History Data API ====================

@router.get(
    "/csv/players",
    response_model=CSVPlayersResponse,
    summary="Get CSV player list",
    description="Get all player names from CSV file (for autocomplete)"
)
async def get_csv_players(
    q: str = Query(default="", description="Search keyword (optional)")
) -> CSVPlayersResponse:
    """
    Get player names from the CSV file

    GET /api/nba/csv/players?q=curry

    This endpoint reads player names from data/nba_player_game_logs.csv
    Used for frontend player autocomplete

    Args:
        q: Search keyword (case-insensitive)

    Returns:
        CSVPlayersResponse: List of player names

    Example Response:
        {
            "players": ["Stephen Curry", "Seth Curry"],
            "total": 2
        }
    """
    try:
        players = csv_player_service.get_all_players(search=q if q else None)
        return CSVPlayersResponse(
            players=players,
            total=len(players)
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read CSV: {str(e)}"
        )


@router.post(
    "/csv/reload",
    summary="Reload CSV data",
    description="Force clear cache and reload CSV file"
)
async def reload_csv():
    """
    Force reload CSV data

    Used for:
    - Refreshing data after CSV file updates
    - Clearing cache after code changes

    POST /api/nba/csv/reload

    Returns:
        dict: Reload result, including player count
    """
    try:
        csv_player_service.reload()
        return {
            "success": True,
            "message": "CSV data reloaded",
            "total_players": len(csv_player_service.get_all_players())
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Reload failed: {str(e)}"
        )


@router.get(
    "/player-history",
    response_model=PlayerHistoryResponse,
    summary="Get player historical stats",
    description="Calculate empirical probability and distribution for player historical data on a specified metric"
)
async def get_player_history(
    player: str = Query(..., description="Player name"),
    metric: str = Query(
        default="points",
        description="Stat metric: points, assists, rebounds, pra (points+rebounds+assists)"
    ),
    threshold: float = Query(..., description="Threshold (e.g. 24.5)"),
    n: int = Query(
        default=0,
        ge=0,
        description="Last N games, 0 means all"
    ),
    bins: int = Query(
        default=15,
        ge=5,
        le=50,
        description="Histogram bins (5-50)"
    ),
    exclude_dnp: bool = Query(
        default=True,
        description="Exclude DNP (Did Not Play, 0 minutes) games"
    ),
    opponent: Optional[str] = Query(
        default=None,
        description="Opponent filter (team name), None means all"
    ),
    is_starter: Optional[bool] = Query(
        default=None,
        description="Starter filter: True (starter only), False (bench only), None (all)"
    ),
    teammate_filter: Optional[str] = Query(
        default=None,
        description="Star teammate filter, comma separated (e.g. 'Giannis Antetokounmpo,Khris Middleton')"
    ),
    teammate_played: Optional[bool] = Query(
        default=None,
        description="Star teammate played filter: True (all played), False (all DNP), None (no filter)"
    ),
    include_playoffs: bool = Query(
        default=False,
        description="Include playoff games. Default is regular season only.",
    ),
    include_play_in: bool = Query(
        default=False,
        description="Include play-in games. Default is regular season only.",
    ),
    season: Optional[str] = Query(
        default=None,
        description=(
            "Season for season_n_games / season_p_over / season_p_under. "
            "2025-26 and 2025-2026 are the same label. Omit it to use the "
            "current NBA season from the recorded ESPN window. n_games, "
            "p_over, and p_under stay the all-games sample."
        ),
    ),
    home_team: Optional[str] = Query(
        default=None,
        description="Event home club. With away_team, teammates are limited to a club in this game.",
    ),
    away_team: Optional[str] = Query(
        default=None,
        description="Event away club. With home_team, teammates are limited to a club in this game.",
    ),
    as_of: Optional[str] = Query(
        default=None,
        description="Event commence time. Selects the log club on that US game date.",
    ),
) -> PlayerHistoryResponse:
    """
    Get player historical statistical summary

    GET /api/nba/player-history?player=Stephen+Curry&metric=points&threshold=24.5
    GET /api/nba/player-history?player=Stephen+Curry&metric=points&threshold=24.5&opponent=Lakers
    GET /api/nba/player-history?player=Stephen+Curry&metric=points&threshold=24.5&is_starter=true

    This endpoint computes the "empirical probability" of a player on a statistic,
    based on historical data, not model predictions!

    Probability definition (aligned with sportsbook props):
    - Over: value > threshold (strictly greater)
    - Under: value < threshold (strictly less)
    - If value == threshold, does not count toward Over or Under

    Args:
        player: Player name
        metric: Statistical metric (points/assists/rebounds/pra)
        threshold: Threshold (can be decimal, e.g. 24.5)
        n: Last N games (0 means use all history)
        bins: Histogram bin number
        exclude_dnp: Whether to exclude DNP games
        opponent: Opponent filter (optional)
        is_starter: Starter status filter (True=only starter, False=only bench, None=all)

    Returns:
        PlayerHistoryResponse: Contains probabilities, mean, stddev, game_logs, opponent list

    Example Response:
        {
            "player": "Stephen Curry",
            "metric": "points",
            "threshold": 24.5,
            "n_games": 68,
            "p_over": 0.47,
            "p_under": 0.53,
            "mean": 25.1,
            "std": 5.7,
            "game_logs": [
                {"date": "01/15", "opponent": "Lakers", "value": 28, "is_over": true},
                ...
            ],
            "opponents": ["Lakers", "Celtics", ...],
            "histogram": [...]
        }
    """
    # 💡 Validate metric param against the services-layer dispatch table
    # so the route stays in lockstep with whatever continuous metrics the
    # service supports. SPO-16 expanded this to 11 continuous keys; future
    # additions to CONTINUOUS_METRIC_EXTRACTORS flow through automatically.
    # Binary metrics (currently only `dd`) flow through `/player-dd-history`,
    # not this route — the error message points there explicitly so a
    # mistaken `metric=dd` caller doesn't silently fail.
    valid_metrics = sorted(CONTINUOUS_METRIC_EXTRACTORS.keys())
    if metric not in valid_metrics:
        hint = ""
        # ⚠ Catch the most likely caller bug: passing a binary key here.
        if metric == "dd" or metric == "double_double":
            hint = (
                " — DD is a binary outcome (Yes/No), not Over/Under. "
                "Use GET /api/nba/player-dd-history instead."
            )
        raise HTTPException(
            status_code=400,
            detail=f"Invalid metric: {metric}. Valid: {valid_metrics}{hint}"
        )
    
    try:
        # Parse teammate_filter comma-separated string to list
        teammate_list = None
        if teammate_filter:
            teammate_list = [t.strip() for t in teammate_filter.split(",") if t.strip()]
        
        # Call CSV service for statistics
        stats = csv_player_service.get_player_stats(
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
            include_playoffs=include_playoffs,
            include_play_in=include_play_in,
            season=season,
            home_team=home_team,
            away_team=away_team,
            as_of=as_of,
        )
        
        # Convert histogram to Pydantic model
        histogram_bins = [
            HistogramBin(
                binStart=bin_data["binStart"],
                binEnd=bin_data["binEnd"],
                count=bin_data["count"]
            )
            for bin_data in stats.get("histogram", [])
        ]
        
        # Convert game_logs to Pydantic model
        game_logs = [
            GameLog(
                date=log["date"],
                date_full=log["date_full"],
                opponent=log["opponent"],
                value=log["value"],
                is_over=log["is_over"],
                team=log.get("team", ""),
                minutes=log.get("minutes", 0.0),  # Playing time
                is_starter=log.get("is_starter", False),  # Starter status
                game_type=coalesce_game_type(log.get("game_type")),
                season=log.get("season", ""),
                home_or_away=log.get("home_or_away"),
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
            teammate_context=[
                TeammateContext.model_validate(item)
                for item in stats.get("teammate_context") or []
            ],
            season=stats.get("season"),
            season_n_games=stats.get("season_n_games"),
            season_p_over=stats.get("season_p_over"),
            season_p_under=stats.get("season_p_under"),
            opponent_filter=stats.get("opponent_filter"),
            teammate_filter=stats.get("teammate_filter"),
            teammate_played=stats.get("teammate_played"),
            message=stats.get("message")
        )
        
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Calculation failed: {str(e)}"
        )


@router.get(
    "/player-dd-history",
    response_model=PlayerDDHistoryResponse,
    summary="Get player Double-Double historical rate",
    description=(
        "Compute historical P(DD = 1) for a player from CSV game logs. "
        "DD is binary (Yes/No) — there is no threshold; use this endpoint "
        "instead of /player-history when the user picks the DD market."
    ),
)
async def get_player_dd_history(
    player: str = Query(
        ...,
        description="Player name (normalized exact match: case, accents, punctuation, suffixes)",
    ),
    season: Optional[str] = Query(
        default=None,
        description="Season filter (e.g. '2024-25'); None means use all seasons",
    ),
    include_playoffs: bool = Query(
        default=False,
        description="Include playoff games. Default is regular season only.",
    ),
    include_play_in: bool = Query(
        default=False,
        description="Include play-in games. Default is regular season only.",
    ),
) -> PlayerDDHistoryResponse:
    """
    Get player Double-Double historical rate.

    GET /api/nba/player-dd-history?player=Nikola+Jokic&season=2024-25

    Delegates to ``csv_player_history.player_dd_history()``. DD definition
    follows the standard NBA convention (≥10 in at least 2 of
    {PTS, REB, AST, STL, BLK}). DNP games are excluded.

    Args:
        player: Player name
        season: Optional season filter (e.g. "2024-25")

    Returns:
        PlayerDDHistoryResponse with prob_dd, dd_games, n_games, message.
    """
    # ⚠ Anti-hallucination guard: DO NOT accept a `threshold` query param —
    # the services-layer method explicitly rejects non-None threshold to
    # catch callers wiring DD through the Over/Under flow by mistake.
    try:
        stats = csv_player_service.player_dd_history(
            player_name=player,
            season=season,
            include_playoffs=include_playoffs,
            include_play_in=include_play_in,
        )

        return PlayerDDHistoryResponse(
            player=stats["player"],
            season=stats.get("season"),
            n_games=stats.get("n_games", 0),
            dd_games=stats.get("dd_games", 0),
            prob_dd=stats.get("prob_dd"),
            message=stats.get("message"),
        )

    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e),
        )
    except ValueError as e:
        # 💡 Defensive: services-layer raises ValueError on misuse (e.g.
        # threshold passed). The route doesn't expose threshold today,
        # but surface the error rather than 500 if it ever leaks.
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"DD history calculation failed: {str(e)}",
        )
