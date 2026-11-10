"""Read every stored player line for one NBA event.

``GET /api/nba/events/{event_id}/props`` is served only from
``odds_line_snapshots``. The scheduler (``odds_snapshot_service``) already
paid for those rows. This module does not import the Odds API gateway or
provider, and a missing snapshot is an empty payload, not a live refresh.

``_main_book_line`` below mirrors ``daily_analysis._main_book_line``
(SPO-115). That helper is not on ``dev``, so this copy stays local.
One of the two copies should be removed after PR #43 merges.
"""

from __future__ import annotations

import logging
import math
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
    """Coerce a numeric American price to int. None stays None.

    Infinity and NaN are not posted prices. Both return None. They do
    not raise. ``int(float("inf"))`` would raise ``OverflowError``, and
    ``int(float("nan"))`` would raise ``ValueError``.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    try:
        return int(number)
    except (TypeError, ValueError, OverflowError):
        return None


def _posted_price(value: Any) -> float | None:
    """American price used by the vote, or None when that side is absent.

    Same cases as ``posted_american_odds``: missing, non-numeric, 0,
    Infinity, and NaN are not a posted leg.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number == 0:
        return None
    return number


def _even_money_distance(over: float | None, under: float | None) -> float:
    """Distance from a fair 50/50 after the vig is removed.

    Two posted sides: divide the Over implied probability by the sum of
    both implied probabilities, then measure how far that is from 0.5.
    One posted side: how far that side's implied probability is from 0.5.
    No price: 1.0, so the rung sorts last among priced rungs.
    """
    if over is not None and under is not None:
        p_over = american_to_prob(over)
        p_under = american_to_prob(under)
        total = p_over + p_under
        if total <= 0:
            return 1.0
        return abs((p_over / total) - 0.5)
    posted = over if over is not None else under
    if posted is None:
        return 1.0
    return abs(american_to_prob(posted) - 0.5)


def _posted_point(points: list[float]) -> float:
    """Mode of the posted points when no side has a usable price.

    Ties: sort the modes and take the middle one when the count is odd,
    or the lower of the two central values when the count is even.
    """
    rounded = [round(point, 1) for point in points]
    counts: dict[float, int] = {}
    for point in rounded:
        counts[point] = counts.get(point, 0) + 1
    most = max(counts.values())
    modes = sorted(point for point, count in counts.items() if count == most)
    if len(modes) % 2 == 1:
        return float(modes[len(modes) // 2])
    return float(modes[(len(modes) // 2) - 1])


def _row_for_rung(rung: dict[str, Any]) -> dict[str, Any]:
    """Return a stored row that carries the rung's kept prices.

    When one stored row already has both kept prices, that row is
    returned unchanged. When the kept Over and the kept Under come from
    different rows at the same point, the result is a copy of the first
    row with those two prices written on it.
    """
    over = rung["over"]
    under = rung["under"]
    for row in rung["rows"]:
        if _posted_price(row.get("over_odds")) == over and _posted_price(row.get("under_odds")) == under:
            return row
    merged = dict(rung["rows"][0])
    merged["line"] = rung["point"]
    merged["over_odds"] = over
    merged["under_odds"] = under
    return merged


def _main_book_line(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the one stored row that this bookmaker is allowed to vote.

    Mirrors ``daily_analysis._main_book_line`` (SPO-115). One of the two
    copies should be removed after PR #43 merges. This copy stays in
    this module so the branch does not import that helper.

    "Main" means the single total that counts. "Book" means one
    bookmaker. "Line" means that total. Call it with every stored row
    for one ``(market, player, bookmaker)`` inside one snapshot.

    The rules, applied to stored rows (``line``, ``over_odds``,
    ``under_odds``) rather than to raw outcomes:

    1. Group rows by the line rounded to one decimal. On a repeated
       side at that line, keep the price closer to even money.
    2. Remove the vig, then keep the pair closest to even money.
       A two-sided rung beats a one-sided Over. Equal distances keep
       the lower line.
    3. When no side has a usable price, the fallback is the mode of
       the posted lines, not the lower line.

    A single stored row is returned unchanged.

    Args:
        rows: Stored rows for a single bookmaker. Must be non-empty.

    Returns:
        The row that votes and that appears in ``books``.
    """
    if len(rows) == 1:
        return rows[0]

    rungs: dict[float, dict[str, Any]] = {}
    bare_points: list[float] = []
    for row in rows:
        line = _as_float(row.get("line"))
        if line is None:
            continue
        point = round(line, 1)
        over = _posted_price(row.get("over_odds"))
        under = _posted_price(row.get("under_odds"))
        bare_points.append(point)
        rung = rungs.get(point)
        if rung is None:
            rungs[point] = {
                "point": point,
                "over": over,
                "under": under,
                "rows": [row],
            }
            continue
        rung["rows"].append(row)
        if over is not None and (
            rung["over"] is None
            or _even_money_distance(over, None) < _even_money_distance(rung["over"], None)
        ):
            rung["over"] = over
        if under is not None and (
            rung["under"] is None
            or _even_money_distance(under, None) < _even_money_distance(rung["under"], None)
        ):
            rung["under"] = under

    if not bare_points:
        return rows[0]

    two_sided = [
        rung
        for rung in rungs.values()
        if rung["over"] is not None and rung["under"] is not None
    ]
    priced = [
        rung
        for rung in rungs.values()
        if rung["over"] is not None or rung["under"] is not None
    ]
    candidates = two_sided or priced
    if not candidates:
        chosen = _posted_point(bare_points)
        for row in rows:
            line = _as_float(row.get("line"))
            if line is not None and round(line, 1) == chosen:
                return row
        return rows[0]

    def _sort_key(rung: dict[str, Any]) -> tuple[float, float]:
        return (_even_money_distance(rung["over"], rung["under"]), rung["point"])

    return _row_for_rung(min(candidates, key=_sort_key))


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
