"""One read for every posted player on an NBA event.

``GET /api/nba/events/{event_id}/reads`` is a separate route from bulk
props. The lines stay on the props route, which is a snapshot read. A
read also starts from that snapshot: the modal line, the book prices at
that line, and nothing from The Odds API. History comes from the NBA
game log. The projection signal is omitted.

``combined_probability`` is ``build_nba_signals``. This module does not
change that math. There is no projection cache read. The projection
signal is omitted. Defense ranks, when the player's club is in the
event, come from the NBA game log.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

from pydantic import ValidationError

from app.models.schemas import (
    BulkPropBook,
    BulkPropPlayer,
    EventReadsResponse,
    PropRead,
)
from app.services.bulk_props import (
    BulkPropsQueryFailed,
    BulkPropsStoreUnavailable,
    assemble_bulk_props,
)
from app.services.cache import cache_service
from app.services.daily_analysis import (
    HIGH_PROBABILITY_THRESHOLD,
    LEAN_PROBABILITY_FLOOR,
    SUPPORTED_MARKETS,
    _empty_rank_fields,
    _opponent_club,
    _recent_stat_values,
    choose_daily_pick_side,
    read_tier,
)
from app.services.db import db_service
from app.services.defense_ranks import defense_fields
from app.services.pick_signals import (
    american_pairs_at_line,
    build_nba_signals,
    no_vig_consensus,
)
logger = logging.getLogger(__name__)

# Same window as the props cache. A new snapshot is visible on the next
# miss. This is not a live-odds TTL: the payload says source "snapshot".
EVENT_READS_CACHE_TTL_SECONDS = 60

_MARKET_TO_METRIC: dict[str, str] = {
    market: metric for market, metric in SUPPORTED_MARKETS
}

# Latest capture. home_team and away_team name the game so a defense
# rank can use the other club. The read itself keys off the player name.
LATEST_EVENT_READ_SQL = """
SELECT
    snapshot_at,
    date,
    home_team,
    away_team,
    player_name,
    market,
    bookmaker,
    line,
    over_odds,
    under_odds
FROM odds_line_snapshots
WHERE event_id = $1
  AND snapshot_at = (
      SELECT MAX(snapshot_at)
      FROM odds_line_snapshots
      WHERE event_id = $1
  )
ORDER BY market ASC, player_name ASC, bookmaker ASC
"""


def event_reads_cache_key(event_id: str, market: str | None) -> str:
    """Redis key for one event and one market filter.

    ``market`` None is every stored market. The key does not include
    ``snapshot_at``. The TTL is 60 seconds, so a new capture shows up
    on the next miss. A one-market request cannot be served as the
    all-markets document.

    Args:
        event_id: Well-formed event id.
        market: One snapshot market key, or None.

    Returns:
        Redis key under ``nba:event-reads:v1``.
    """
    market_part = "*" if not market else market
    return f"nba:event-reads:v1:{event_id}:m={market_part}"


def choose_read_side(
    p_over: float | None,
    p_under: float | None,
) -> tuple[str | None, float | None]:
    """Choose the side of a posted player, including rates below Lean.

    The first two steps match a stored daily pick: over wins when both
    sides clear 0.65, otherwise a side that clears 0.56. Below that
    floor the higher historical rate is the side, and a tie stays over.
    ``(None, None)`` when both rates are missing. The caller may then
    use the no-vig favorite.

    Args:
        p_over: Share of prior games strictly above the line.
        p_under: Share of prior games strictly below the line.

    Returns:
        ``("over"|"under", rate)`` rounded to 4 decimals, or
        ``(None, None)``.
    """
    side, probability = choose_daily_pick_side(
        p_over, p_under, HIGH_PROBABILITY_THRESHOLD
    )
    if side is not None:
        return side, probability
    side, probability = choose_daily_pick_side(
        p_over, p_under, LEAN_PROBABILITY_FLOOR
    )
    if side is not None:
        return side, probability
    over = _finite_rate(p_over)
    under = _finite_rate(p_under)
    if over is None and under is None:
        return None, None
    if under is None or (over is not None and over >= under):
        return "over", round(over, 4) if over is not None else None
    return "under", round(under, 4)


def _finite_rate(value: float | None) -> float | None:
    """A finite rate, or None. Booleans are not rates."""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def bookmakers_at_books(
    player_name: str,
    market: str,
    books: list[BulkPropBook],
) -> list[dict[str, Any]]:
    """Odds-API-shaped books built from stored snapshot rows.

    ``build_nba_signals`` reads ``bookmakers[].markets[].outcomes[]``.
    The snapshot row is not that shape. This rebuilds only the prices
    the snapshot stored, at that book's line. It does not invent a
    price. A null side is omitted. A binary book's Yes/No prices are
    not passed through, because those fields are null on ``BulkPropBook``
    for the over/under pair and this helper only copies Over and Under.

    Args:
        player_name: Outcome ``description``. Must match the snapshot name.
        market: Market key placed on the synthetic market object.
        books: One entry per bookmaker after the one-vote collapse.

    Returns:
        One dict per book that posted at least one Over or Under price.
    """
    built: list[dict[str, Any]] = []
    for book in books:
        outcomes: list[dict[str, Any]] = []
        if book.over_odds is not None:
            outcomes.append(
                {
                    "name": "Over",
                    "description": player_name,
                    "price": book.over_odds,
                    "point": book.line,
                }
            )
        if book.under_odds is not None:
            outcomes.append(
                {
                    "name": "Under",
                    "description": player_name,
                    "price": book.under_odds,
                    "point": book.line,
                }
            )
        if not outcomes:
            continue
        built.append(
            {
                "key": book.bookmaker,
                "markets": [{"key": market, "outcomes": outcomes}],
            }
        )
    return built


def _market_favorite(bookmakers: list[dict[str, Any]], player_name: str, line: float) -> str | None:
    """No-vig favorite at ``line``. Over wins a tie. None when no pair de-vigs."""
    consensus = no_vig_consensus(american_pairs_at_line(bookmakers, player_name, line))
    if consensus is None:
        return None
    over_probability, under_probability = consensus
    if over_probability >= under_probability:
        return "over"
    return "under"


def _text_or_none(value: Any) -> str | None:
    """A non-empty string, or None. A mock or a blank is None."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _event_sides(rows: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Home and away from the first snapshot row that has both."""
    for row in rows:
        home = _text_or_none(row.get("home_team"))
        away = _text_or_none(row.get("away_team"))
        if home and away:
            return home, away
    return None, None


def _ranks_for_player(
    player_name: str,
    home_team: str | None,
    away_team: str | None,
    csv_service: Any,
) -> dict[str, Any]:
    """CSV defense ranks when the player's latest club is in this event.

    ``latest_team`` and ``latest_position`` are the game-log fields.
    A service that does not have them leaves the ranks null. Injury
    status is not read from a lineup snapshot here.
    """
    empty = _empty_rank_fields()
    latest_team = getattr(csv_service, "latest_team", None)
    latest_position = getattr(csv_service, "latest_position", None)
    team = _text_or_none(latest_team(player_name) if callable(latest_team) else None)
    position = _text_or_none(
        latest_position(player_name) if callable(latest_position) else None
    )
    if not team or not home_team or not away_team:
        return empty
    try:
        opponent = _opponent_club(team, home_team, away_team, "nba")
        return defense_fields(opponent, position)
    except Exception:
        logger.exception("Defense-rank fill failed for %s", player_name)
        return empty


def _read_for_player(
    *,
    market: str,
    player: BulkPropPlayer,
    csv_service: Any,
    home_team: str | None,
    away_team: str | None,
) -> PropRead:
    """Build one read. The player is returned even when every score is null."""
    metric = _MARKET_TO_METRIC.get(market)
    if metric is None:
        return PropRead(
            player=player.player,
            market=market,
            line=player.line,
            side=None,
            combined_probability=None,
            tier=None,
            signals=None,
        )
    stats = csv_service.get_player_stats(
        player_name=player.player,
        metric=metric,
        threshold=player.line,
        n=0,
        exclude_dnp=True,
    )
    side, rate = choose_read_side(stats.get("p_over"), stats.get("p_under"))
    bookmakers = bookmakers_at_books(player.player, market, player.books)
    if side is None:
        side = _market_favorite(bookmakers, player.player, player.line)
        rate = None
    if side is None:
        return PropRead(
            player=player.player,
            market=market,
            line=player.line,
            side=None,
            combined_probability=None,
            tier=None,
            signals=None,
        )
    values = _recent_stat_values(stats.get("game_logs") or [])
    last10 = values[-10:] if len(values) >= 10 else None
    ranks = _ranks_for_player(player.player, home_team, away_team, csv_service)
    signals, combined, _adjustment = build_nba_signals(
        side=side,
        line=player.line,
        player_name=player.player,
        bookmakers=bookmakers,
        last10_values=last10,
        history_rate=rate,
        projected_value=None,
        opponent_rank=ranks["opponent_rank"],
        opponent_position_rank=ranks["opponent_position_rank"],
        injury_status=None,
    )
    return PropRead(
        player=player.player,
        market=market,
        line=player.line,
        side=side,
        combined_probability=combined,
        tier=read_tier(combined),
        signals=signals,
    )


def assemble_event_reads(
    event_id: str,
    rows: list[dict[str, Any]],
    *,
    market: str | None = None,
    csv_service: Any | None = None,
) -> EventReadsResponse:
    """Build one read per posted player. No I/O of its own besides the CSV service.

    ``rows`` are snapshot rows. ``assemble_bulk_props`` picks the newest
    capture, one vote per book, and the modal line. This function then
    scores that line. A binary market is included with a null side.
    The projection signal is omitted. Defense ranks use the game log
    when the player's latest club is home or away on these rows.

    Args:
        event_id: Event id echoed on the response.
        rows: Snapshot rows for the event. Older captures are ignored.
        market: One market key, or None for every stored market.
        csv_service: NBA history service. Defaults to the process singleton.

    Returns:
        The reads payload. ``source`` is ``"snapshot"``.
    """
    if csv_service is None:
        from app.services.csv_player_history import csv_player_service

        csv_service = csv_player_service
    home_team, away_team = _event_sides(rows)
    markets = frozenset({market}) if market else None
    props = assemble_bulk_props(event_id, rows, markets=markets)
    reads: list[PropRead] = []
    for item in props.markets:
        for player in item.players:
            reads.append(
                _read_for_player(
                    market=item.market,
                    player=player,
                    csv_service=csv_service,
                    home_team=home_team,
                    away_team=away_team,
                )
            )
    return EventReadsResponse(
        event_id=event_id,
        market=market,
        snapshot_at=props.snapshot_at,
        source="snapshot",
        reads=reads,
    )


async def get_event_reads(
    event_id: str,
    *,
    market: str | None = None,
    csv_service: Any | None = None,
) -> EventReadsResponse:
    """Return a read for every posted player on one NBA event.

    Redis first, for 60 seconds. On a miss, read the latest
    ``odds_line_snapshots`` capture. Do not call the Odds API on a hit,
    a miss, a cache failure, or a database failure. An empty capture is
    cached too, so a cold event cannot become a live quote. This does
    not read a projection cache.

    Args:
        event_id: Well-formed event id. The route checks the shape.
        market: One snapshot market key, or None for every stored market.
        csv_service: History service override, used by tests.

    Returns:
        Reads payload. ``source`` is ``"snapshot"``.

    Raises:
        BulkPropsStoreUnavailable: Postgres has no connection pool.
        BulkPropsQueryFailed: The snapshot query raised.
    """
    if market is not None:
        market = market.strip() or None
    key = event_reads_cache_key(event_id, market)
    cached = await cache_service.get(key)
    if cached is not None:
        try:
            return EventReadsResponse.model_validate(cached)
        except ValidationError:
            logger.warning("Ignoring unreadable event-reads cache entry %s", key)

    if not db_service.is_connected:
        raise BulkPropsStoreUnavailable(
            "PostgreSQL is not connected, cannot read odds snapshots"
        )
    try:
        rows = await db_service.fetch(LATEST_EVENT_READ_SQL, event_id)
    except Exception as exc:
        logger.exception("Event reads query failed for event %s", event_id)
        raise BulkPropsQueryFailed("Failed to read odds snapshots") from exc

    payload = await asyncio.to_thread(
        assemble_event_reads,
        event_id,
        rows,
        market=market,
        csv_service=csv_service,
    )
    await cache_service.set(
        key,
        payload.model_dump(mode="json"),
        EVENT_READS_CACHE_TTL_SECONDS,
    )
    return payload
