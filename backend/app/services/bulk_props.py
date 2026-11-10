"""Read every stored player line for one NBA event.

``GET /api/nba/events/{event_id}/props`` is served only from
``odds_line_snapshots``. The scheduler (``odds_snapshot_service``) already
paid for those rows. This module does not import the Odds API gateway or
provider, and a missing snapshot is an empty payload, not a live refresh.

SPO-115's ``_main_book_line`` is not on ``dev``. ``_main_book_line`` below
is the local stand-in: one bookmaker, one vote.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app.models.schemas import (
    BulkPropBook,
    BulkPropMarket,
    BulkPropPlayer,
    BulkPropsResponse,
)
from app.services.cache import cache_service
from app.services.db import db_service
from app.services.odds_snapshot_service import (
    BINARY_MARKET_KEYS,
    OVER_UNDER_MARKET_KEYS,
    SNAPSHOT_MARKETS,
)
from app.services.prob import american_to_prob, calculate_mode_threshold

logger = logging.getLogger(__name__)

# Repeat reads of one assembled snapshot. The underlying rows change only
# when the scheduler writes a new capture (three times a day). This is not
# a live-odds TTL: a miss reads Postgres and never calls the Odds API.
BULK_PROPS_CACHE_TTL_SECONDS = 60

_MARKET_ORDER = tuple(part for part in SNAPSHOT_MARKETS.split(",") if part)
_ALLOWED_MARKETS = OVER_UNDER_MARKET_KEYS | BINARY_MARKET_KEYS
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

# Latest capture for one event. ``MAX(snapshot_at)`` keeps an older
# capture from voting again. The read never joins an odds provider.
LATEST_EVENT_SNAPSHOT_SQL = """
SELECT
    snapshot_at,
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


class UnknownMarkets(ValueError):
    """The ``markets`` query named a key this snapshot job does not store."""

    def __init__(self, unknown: list[str]) -> None:
        self.unknown = unknown
        self.valid = sorted(_ALLOWED_MARKETS)
        super().__init__(
            f"Unknown markets: {unknown}. Valid values: {self.valid}"
        )


class BulkPropsStoreUnavailable(Exception):
    """Postgres is down. Callers must not fall through to the Odds API."""


class BulkPropsQueryFailed(Exception):
    """The snapshot read failed. Callers must not fall through to the Odds API."""


def event_id_is_well_formed(event_id: str) -> bool:
    """Return whether ``event_id`` is safe to look up.

    Well-formed ids are 1 to 128 characters from ``[A-Za-z0-9_-]``, starting
    with a letter or digit. The Odds API's 32-character hex ids match, and
    so do ids that contain hyphens. Anything else is malformed: the route
    answers 404 and does not query Postgres. A well-formed id with no stored
    snapshot is a normal empty 200, not a 404.

    Args:
        event_id: Path parameter from ``/api/nba/events/{event_id}/props``.

    Returns:
        True when the id may be used as a snapshot key.
    """
    return _EVENT_ID_RE.fullmatch(event_id) is not None


def parse_market_filter(raw: str | None) -> frozenset[str] | None:
    """Parse the optional comma-separated ``markets`` query.

    ``None``, an empty string, and a string of only commas mean "every
    market present in the snapshot". Each token is stripped. A token that
    is not in ``OVER_UNDER_MARKET_KEYS`` or ``BINARY_MARKET_KEYS`` raises
    ``UnknownMarkets`` so the route can answer 400.

    Args:
        raw: The query string, or None when the client omitted it.

    Returns:
        A set of market keys, or None when the client did not filter.

    Raises:
        UnknownMarkets: At least one token is not a snapshot market.
    """
    if raw is None or not raw.strip():
        return None
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        return None
    unknown = [part for part in parts if part not in _ALLOWED_MARKETS]
    if unknown:
        raise UnknownMarkets(unknown)
    return frozenset(parts)


def bulk_props_cache_key(
    event_id: str,
    markets: frozenset[str] | None,
    player: str | None,
) -> str:
    """Cache key for one assembled response.

    The key includes the market filter and the player filter so a request
    for one player cannot be served as the full board. Player matching is
    case-insensitive, and the key uses the case-folded name so ``Luka``
    and ``luka`` share an entry. TTL is ``BULK_PROPS_CACHE_TTL_SECONDS``.

    Args:
        event_id: Well-formed event id.
        markets: Market filter, or None for every stored market.
        player: Player filter, or None for every player.

    Returns:
        Redis key under ``nba:bulk-props:v1``.
    """
    market_part = "*" if not markets else ",".join(sorted(markets))
    player_part = "*" if not player else player.casefold()
    return f"nba:bulk-props:v1:{event_id}:m={market_part}:p={player_part}"


def _as_datetime(value: Any) -> datetime | None:
    """Normalize a snapshot timestamp to aware UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_float(value: Any) -> float | None:
    """Coerce a numeric DB value to float. None stays None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    """Coerce a numeric American price to int. None stays None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _distance_from_even(price: int | None) -> float:
    """How far an American price is from a 50 percent implied probability.

    A missing price sorts last, so a row that actually posted a number
    wins over an empty one. ``american_to_prob`` rejects 0; that row also
    sorts last.
    """
    if price is None:
        return float("inf")
    try:
        return abs(american_to_prob(float(price)) - 0.5)
    except (TypeError, ValueError, ZeroDivisionError):
        return float("inf")


def _main_book_line(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the one stored row that this bookmaker is allowed to vote.

    The name is the local stand-in for SPO-115 ``_main_book_line``, which
    is not on ``dev``. "Main" means the single total that counts. "Book"
    means one bookmaker. "Line" means that total.

    Call it with every stored row for one ``(market, player, bookmaker)``
    inside one snapshot. A book that posted several alternate totals must
    not receive several votes in ``calculate_mode_threshold``. The winning
    row is the one whose Over price (Yes price for a binary market, stored
    in the same ``over_odds`` column) is closest to a 50 percent implied
    probability. Ties break toward the American price closer to -110, then
    the lower line, then the numeric prices, so the choice does not depend
    on row order.

    One row is returned unchanged.

    Args:
        rows: Stored rows for a single bookmaker. Must be non-empty.

    Returns:
        The row that votes and that appears in ``books``.
    """
    if len(rows) == 1:
        return rows[0]

    def vote_key(row: dict[str, Any]) -> tuple[float, float, float, int, int]:
        price = _as_int(row.get("over_odds"))
        line = _as_float(row.get("line"))
        under = _as_int(row.get("under_odds"))
        return (
            _distance_from_even(price),
            abs(price - (-110)) if price is not None else float("inf"),
            line if line is not None else float("inf"),
            price if price is not None else 0,
            under if under is not None else 0,
        )

    return min(rows, key=vote_key)


def _age_seconds(snapshot_at: datetime, now: datetime) -> int:
    """Whole seconds from ``snapshot_at`` to ``now``, never negative."""
    stamp = _as_datetime(snapshot_at)
    clock = _as_datetime(now)
    if stamp is None or clock is None:
        return 0
    return max(0, int((clock - stamp).total_seconds()))


def _book_from_row(market: str, row: dict[str, Any]) -> BulkPropBook | None:
    """Map one stored row onto the book object the route returns.

    Over/Under markets fill ``over_odds`` and ``under_odds``. ``yes_odds``
    and ``no_odds`` are null. Binary markets (``player_double_double``)
    store Yes in ``over_odds`` and No in ``under_odds``. The response puts
    those prices on ``yes_odds`` and ``no_odds`` and leaves the Over/Under
    fields null, so a Yes price is not read as an Over. A missing No stays
    null. It is not copied from Yes.

    A row with no line is dropped. The binary writer stores the 0.5
    sentinel, so a binary row still has a line.
    """
    line = _as_float(row.get("line"))
    bookmaker = row.get("bookmaker")
    if line is None or not bookmaker:
        return None
    stored_over = _as_int(row.get("over_odds"))
    stored_under = _as_int(row.get("under_odds"))
    if market in BINARY_MARKET_KEYS:
        return BulkPropBook(
            bookmaker=str(bookmaker),
            line=line,
            over_odds=None,
            under_odds=None,
            yes_odds=stored_over,
            no_odds=stored_under,
        )
    return BulkPropBook(
        bookmaker=str(bookmaker),
        line=line,
        over_odds=stored_over,
        under_odds=stored_under,
        yes_odds=None,
        no_odds=None,
    )


def _market_rank(market: str) -> tuple[int, int | str]:
    """SNAPSHOT_MARKETS order, then any unexpected stored key."""
    try:
        return (0, _MARKET_ORDER.index(market))
    except ValueError:
        return (1, market)


def assemble_bulk_props(
    event_id: str,
    rows: list[dict[str, Any]],
    *,
    markets: frozenset[str] | None = None,
    player: str | None = None,
    now: datetime | None = None,
) -> BulkPropsResponse:
    """Build the response from snapshot rows. No I/O.

    Only rows at the newest ``snapshot_at`` are used, so an older capture
    mixed into the list cannot add a second vote. ``markets`` and
    ``player`` narrow that newest capture. They do not clear
    ``snapshot_at``: a filter that matches nobody still reports when the
    snapshot was taken. No rows at all means ``snapshot_at`` and
    ``data_age_seconds`` are null and ``markets`` is empty.

    Each bookmaker votes once (``_main_book_line``). The player's ``line``
    is ``calculate_mode_threshold`` of those votes, the same modal rule
    daily picks use. ``bookmakers_count`` is the number of distinct books
    after that collapse, which is also ``len(books)``.

    Args:
        event_id: Event id echoed on the response.
        rows: Snapshot rows, usually the latest capture.
        markets: Keep these market keys, or None to keep every stored market.
        player: Exact player name, case-insensitive, or None for every player.
        now: Clock for ``data_age_seconds``. Defaults to aware UTC now.

    Returns:
        The bulk-props payload. ``source`` is always ``"snapshot"``.
    """
    clock = now or datetime.now(timezone.utc)
    if not markets:
        markets = None
    wanted = player.casefold() if player and player.strip() else None

    stamped: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        stamp = _as_datetime(row.get("snapshot_at"))
        if stamp is None:
            continue
        stamped.append((stamp, row))

    if not stamped:
        return BulkPropsResponse(
            event_id=event_id,
            snapshot_at=None,
            data_age_seconds=None,
            source="snapshot",
            markets=[],
        )

    latest = max(stamp for stamp, _row in stamped)
    current = [row for stamp, row in stamped if stamp == latest]

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in current:
        market = str(row.get("market") or "")
        player_name = str(row.get("player_name") or "")
        bookmaker = str(row.get("bookmaker") or "")
        if not market or not player_name or not bookmaker:
            continue
        if markets is not None and market not in markets:
            continue
        if wanted is not None and player_name.casefold() != wanted:
            continue
        grouped.setdefault((market, player_name, bookmaker), []).append(row)

    by_market: dict[str, dict[str, list[BulkPropBook]]] = {}
    for (market, player_name, _bookmaker), group in grouped.items():
        chosen = _main_book_line(group)
        book = _book_from_row(market, chosen)
        if book is None:
            continue
        by_market.setdefault(market, {}).setdefault(player_name, []).append(book)

    market_models: list[BulkPropMarket] = []
    for market in sorted(by_market, key=_market_rank):
        players: list[BulkPropPlayer] = []
        for player_name in sorted(by_market[market], key=str.casefold):
            books = sorted(by_market[market][player_name], key=lambda item: item.bookmaker.casefold())
            voted_lines = [item.line for item in books]
            mode = calculate_mode_threshold(voted_lines)
            if mode is None:
                continue
            players.append(
                BulkPropPlayer(
                    player=player_name,
                    line=float(mode),
                    bookmakers_count=len(books),
                    books=books,
                )
            )
        if players:
            market_models.append(BulkPropMarket(market=market, players=players))

    return BulkPropsResponse(
        event_id=event_id,
        snapshot_at=latest,
        data_age_seconds=_age_seconds(latest, clock),
        source="snapshot",
        markets=market_models,
    )


def _with_fresh_age(payload: BulkPropsResponse, now: datetime) -> BulkPropsResponse:
    """Recompute ``data_age_seconds`` from the cached ``snapshot_at``."""
    if payload.snapshot_at is None:
        return payload
    return payload.model_copy(
        update={"data_age_seconds": _age_seconds(payload.snapshot_at, now)}
    )


async def get_event_bulk_props(
    event_id: str,
    *,
    markets: frozenset[str] | None = None,
    player: str | None = None,
    now: datetime | None = None,
) -> BulkPropsResponse:
    """Return stored lines for every player in one NBA event.

    Looks up a short Redis copy of the assembled response first. On a miss,
    reads the latest ``odds_line_snapshots`` capture for ``event_id``. Does
    not call the Odds API gateway or provider, including when Postgres has
    no row for the event. The empty result is cached too, for
    ``BULK_PROPS_CACHE_TTL_SECONDS``, so a missing game does not become a
    live fetch.

    ``cache_service.set`` JSON-encodes the value it is given. The cached
    document is ``model_dump(mode="json")`` (a dict whose timestamps are
    already strings). Passing ``model_dump_json()`` would store a JSON
    string inside another JSON string. The deprecated ``.json()`` method
    is not used.

    Args:
        event_id: Well-formed event id. The route checks the shape.
        markets: Market keys to keep, or None for every stored market.
        player: Exact player name, case-insensitive, or None.
        now: Clock for ``data_age_seconds``. Defaults to aware UTC now.

    Returns:
        Bulk props payload. ``source`` is ``"snapshot"``.

    Raises:
        BulkPropsStoreUnavailable: Postgres has no connection pool.
        BulkPropsQueryFailed: The snapshot query raised.
    """
    clock = now or datetime.now(timezone.utc)
    if not markets:
        markets = None
    if player is not None:
        player = player.strip() or None
    key = bulk_props_cache_key(event_id, markets, player)

    cached = await cache_service.get(key)
    if cached is not None:
        try:
            payload = BulkPropsResponse.model_validate(cached)
        except ValidationError:
            logger.warning("Ignoring unreadable bulk-props cache entry %s", key)
        else:
            return _with_fresh_age(payload, clock)

    if not db_service.is_connected:
        raise BulkPropsStoreUnavailable(
            "PostgreSQL is not connected, cannot read odds snapshots"
        )

    try:
        rows = await db_service.fetch(LATEST_EVENT_SNAPSHOT_SQL, event_id)
    except Exception as exc:
        logger.exception("Bulk props query failed for event %s", event_id)
        raise BulkPropsQueryFailed("Failed to read odds snapshots") from exc

    payload = assemble_bulk_props(
        event_id,
        rows,
        markets=markets,
        player=player,
        now=clock,
    )
    if not payload.markets:
        logger.info(
            "Bulk props snapshot empty for event %s (markets=%s player=%s)",
            event_id,
            sorted(markets) if markets else "*",
            player or "*",
        )
    await cache_service.set(
        key,
        payload.model_dump(mode="json"),
        BULK_PROPS_CACHE_TTL_SECONDS,
    )
    return payload
