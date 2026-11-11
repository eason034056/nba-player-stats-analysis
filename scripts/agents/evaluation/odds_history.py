"""Historical opening and closing lines for ROI and closing-line value.

The repository does not ship sportsbook history. This module is the hook
that starts working once that history exists. Two inputs are accepted:

* A CSV or JSONL file with one row per player prop, already reduced to an
  opening line and a closing line, both with two-sided American prices.
* Snapshot rows shaped like ``odds_line_snapshots`` (many timestamps per
  prop). ``open_close_from_snapshots`` reduces those to the earliest and
  latest snapshot per prop.

When the loader returns no quotes, ``OddsHistory.active`` is false. Callers
skip pricing and CLV and keep the assumed -110 proxy-line accounting.

Probability CLV and line CLV answer different questions.

Probability CLV is the closing vig-free probability of the side that was
bet, minus the opening vig-free probability of that same side. It changes
only when the two-sided price changes. A line can move while both the open
and the close are -110/-110. After ``prob.devig`` each fair probability is
0.5, so probability CLV is 0. That is not "the bet beat the close"; the
close was the same price.

Line CLV is the closing line minus the opening line for an over, and the
opposite for an under. Positive means the line moved in the bettor's favor.
It can be non-zero on the same quote whose probability CLV is 0.

Vig is removed with ``prob.devig`` (multiplicative normalization), the same
function the live odds path uses.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, ConfigDict, ValidationError

from evaluation.paths import bootstrap

logger = logging.getLogger(__name__)

# Assumed juice when no historical price is attached to a pick.
ASSUMED_AMERICAN_ODDS = -110

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d")


class PropOddsQuote(BaseModel):
    """Opening and closing price for one player prop.

    ``market`` is the CSV metric key (``points``, ``rebounds``, …) or The
    Odds API key (``player_points``). The loader stores the metric key.
    Prices are American odds for both sides. Both sides are required so the
    vig can be removed before CLV is computed.
    """

    model_config = ConfigDict(extra="ignore")

    league: str
    player: str
    game_date: str
    market: str
    open_line: float
    open_over_price: int
    open_under_price: int
    close_line: float
    close_over_price: int
    close_under_price: int
    book: str | None = None


@dataclass
class OddsHistory:
    """Index of quotes keyed by league, player, date, and metric.

    Attributes:
        quotes: Lookup table. The key is
            ``(league, player_key, YYYY-MM-DD, metric)``.
        source: Where the quotes came from. ``None`` when the hook was not
            given a file.
        skipped_rows: Rows that failed validation and were dropped.
        duplicate_keys: Extra rows for a key that was already present. The
            last valid row wins.
    """

    quotes: dict[tuple[str, str, str, str], PropOddsQuote] = field(default_factory=dict)
    source: str | None = None
    skipped_rows: int = 0
    duplicate_keys: int = 0

    @property
    def active(self) -> bool:
        """True when at least one quote was loaded."""
        return bool(self.quotes)

    def lookup(
        self, league: str, player: str, game_date: str, market: str
    ) -> PropOddsQuote | None:
        """Return the quote for this prop, or None when the hook has no row."""
        return self.quotes.get((league.lower(), player_key(player), game_date, market))


def player_key(name: str) -> str:
    """Case-fold a player name and collapse internal whitespace."""
    return " ".join(name.casefold().split())


def inactive_history() -> OddsHistory:
    """An empty history. ``active`` is false and every lookup misses."""
    return OddsHistory()


def unit_profit(american_odds: int, won: bool | None) -> float:
    """Profit on a 1-unit stake at American odds.

    A loss returns -1. A win at negative odds returns ``100 / abs(odds)``
    (so -110 wins ``100/110``). A win at positive odds returns ``odds/100``.

    Args:
        american_odds: Price of the side that was bet. Zero is invalid.
        won: True for a win, False for a loss, None for a push. A push
            refunds the stake, so the profit is 0. It is not a loss.

    Returns:
        Profit in stake units.

    Raises:
        ValueError: If ``american_odds`` is 0.
    """
    if american_odds == 0:
        raise ValueError("Odds cannot be 0")
    if won is None:
        return 0.0
    if not won:
        return -1.0
    if american_odds < 0:
        return 100.0 / abs(american_odds)
    return american_odds / 100.0


def _metric_alias() -> dict[str, str]:
    bootstrap()
    from app.services.daily_analysis import SUPPORTED_MARKETS

    alias: dict[str, str] = {}
    for odds_key, metric in SUPPORTED_MARKETS:
        alias[odds_key.lower()] = metric
        alias[metric.lower()] = metric
    return alias


def normalize_game_date(value: str) -> str:
    """Normalize a date string to ``YYYY-MM-DD``.

    Raises:
        ValueError: If ``value`` matches none of the accepted formats.
    """
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Unrecognised game date: {value!r}")


def _fair_side(over_price: int, under_price: int, side: str) -> float:
    bootstrap()
    from app.services.prob import american_to_prob, devig

    fair_over, fair_under = devig(
        american_to_prob(over_price), american_to_prob(under_price)
    )
    if side == "over":
        return fair_over
    if side == "under":
        return fair_under
    raise ValueError(f"side must be 'over' or 'under', got {side!r}")


def closing_line_value(quote: PropOddsQuote, side: str) -> tuple[float, float]:
    """Closing-line value of ``side`` against this quote.

    Args:
        quote: Opening and closing lines with two-sided American prices.
        side: ``"over"`` or ``"under"``.

    Returns:
        ``(clv_prob, clv_line)``. ``clv_prob`` is the closing vig-free
        probability of ``side`` minus the opening vig-free probability.
        ``clv_line`` is how far the line moved in the bettor's favor
        (positive when an over's line went up, or an under's line went down).
    """
    clv_prob = _fair_side(
        quote.close_over_price, quote.close_under_price, side
    ) - _fair_side(quote.open_over_price, quote.open_under_price, side)
    if side == "over":
        clv_line = quote.close_line - quote.open_line
    else:
        clv_line = quote.open_line - quote.close_line
    return clv_prob, clv_line


def _quote_from_mapping(raw: Mapping[str, Any], alias: dict[str, str]) -> PropOddsQuote:
    market_raw = str(raw.get("market", "")).strip().lower()
    market = alias.get(market_raw, market_raw)
    payload = {
        "league": str(raw.get("league", "nba")).strip().lower() or "nba",
        "player": str(raw.get("player", "")).strip(),
        "game_date": normalize_game_date(str(raw.get("game_date", ""))),
        "market": market,
        "open_line": raw.get("open_line"),
        "open_over_price": raw.get("open_over_price"),
        "open_under_price": raw.get("open_under_price"),
        "close_line": raw.get("close_line"),
        "close_over_price": raw.get("close_over_price"),
        "close_under_price": raw.get("close_under_price"),
        "book": (str(raw["book"]).strip() if raw.get("book") else None),
    }
    quote = PropOddsQuote.model_validate(payload)
    # Reject a zero price here so a bad row is skipped instead of crashing
    # the replay when the profit is computed.
    for price in (
        quote.open_over_price,
        quote.open_under_price,
        quote.close_over_price,
        quote.close_under_price,
    ):
        if price == 0:
            raise ValueError("Odds cannot be 0")
    return quote


def _index_quotes(quotes: Iterable[PropOddsQuote], source: str | None) -> OddsHistory:
    history = OddsHistory(source=source)
    for quote in quotes:
        key = (
            quote.league.lower(),
            player_key(quote.player),
            quote.game_date,
            quote.market,
        )
        if key in history.quotes:
            history.duplicate_keys += 1
        history.quotes[key] = quote
    return history


def load_odds_history(path: str | None) -> OddsHistory:
    """Load opening and closing lines, or return an inactive history.

    Args:
        path: CSV or JSONL file. ``None`` means the caller did not supply
            history, and the hook stays inactive. An empty file is also
            inactive. A path that does not exist raises, because a typo
            should not silently fall back to assumed -110.

    Returns:
        An ``OddsHistory``. Check ``active`` before pricing bets.

    Raises:
        FileNotFoundError: If ``path`` is set and the file is missing.
        ValueError: If the suffix is not ``.csv`` or ``.jsonl``.
    """
    if path is None:
        return inactive_history()
    alias = _metric_alias()
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            text = handle.read()
    except FileNotFoundError:
        raise
    if not text.strip():
        logger.info("Odds history %s is empty; CLV hook stays inactive", path)
        return OddsHistory(source=path)

    quotes: list[PropOddsQuote] = []
    skipped = 0
    suffix = path.rsplit(".", 1)[-1].lower()
    if suffix == "csv":
        reader = csv.DictReader(text.splitlines())
        for raw in reader:
            if not raw or not any((value or "").strip() for value in raw.values()):
                continue
            try:
                quotes.append(_quote_from_mapping(raw, alias))
            except (ValidationError, ValueError) as exc:
                skipped += 1
                logger.warning("Skipping odds row: %s", exc)
    elif suffix == "jsonl":
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                quotes.append(_quote_from_mapping(json.loads(line), alias))
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                skipped += 1
                logger.warning("Skipping odds JSONL line %s: %s", line_no, exc)
    else:
        raise ValueError(f"Odds history must be .csv or .jsonl, got {path!r}")

    history = _index_quotes(quotes, path)
    history.skipped_rows = skipped
    if not history.active:
        logger.info("Odds history %s produced no quotes; CLV hook stays inactive", path)
    return history


def open_close_from_snapshots(
    snapshots: Iterable[Mapping[str, Any]],
    *,
    league: str = "nba",
    book: str | None = None,
) -> OddsHistory:
    """Reduce ``odds_line_snapshots``-shaped rows to open and close quotes.

    Each book contributes one line per ``snapshot_at``: the main line from
    ``bulk_props._main_book_line``. Alternate rungs at that same timestamp
    are not an open or a close. The earliest of those main lines is the
    open. The latest is the close. Rows missing a line or either price are
    skipped. When several books cover the same prop, the alphabetically
    first bookmaker is kept so the choice does not depend on file order.
    Pass ``book`` to keep one bookmaker only.

    Args:
        snapshots: Mappings with ``player_name`` or ``player``, ``date`` or
            ``game_date``, ``market``, ``line``, ``over_odds``, ``under_odds``,
            ``snapshot_at``, and ``bookmaker`` or ``book``. ``league`` on the
            row overrides the ``league`` argument.
        league: League stamped on rows that do not carry one. The snapshot
            table has no league column; exports of that table should pass
            this explicitly.
        book: If set, drop every other bookmaker.

    Returns:
        An ``OddsHistory`` that is inactive when nothing survived.
    """
    alias = _metric_alias()
    grouped: dict[
        tuple[str, str, str, str, str], list[tuple[datetime, Mapping[str, Any]]]
    ] = {}
    skipped = 0
    for raw in snapshots:
        stamp = raw.get("snapshot_at")
        try:
            when = _parse_timestamp(stamp)
            line = float(raw["line"])
            over_odds = int(raw["over_odds"])
            under_odds = int(raw["under_odds"])
            if over_odds == 0 or under_odds == 0:
                raise ValueError("Odds cannot be 0")
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        row_league = str(raw.get("league", league) or league).strip().lower()
        player = str(raw.get("player") or raw.get("player_name") or "").strip()
        date_raw = raw.get("game_date") or raw.get("date")
        bookmaker = str(raw.get("bookmaker") or raw.get("book") or "").strip()
        market_raw = str(raw.get("market", "")).strip().lower()
        try:
            game_date = normalize_game_date(str(date_raw))
        except ValueError:
            skipped += 1
            continue
        if not player or not market_raw:
            skipped += 1
            continue
        if book is not None and bookmaker.lower() != book.lower():
            continue
        metric = alias.get(market_raw, market_raw)
        key = (row_league, player_key(player), game_date, metric, bookmaker.lower())
        grouped.setdefault(key, []).append(
            (
                when,
                {
                    "line": line,
                    "over_odds": over_odds,
                    "under_odds": under_odds,
                    "player": player,
                    "book": bookmaker or None,
                },
            )
        )

    for key, samples in grouped.items():
        grouped[key] = _main_line_per_snapshot(samples)

    # One quote per prop. Alphabetical bookmaker wins ties across books.
    by_prop: dict[tuple[str, str, str, str], tuple[str, list]] = {}
    for key, samples in grouped.items():
        prop = key[:4]
        bookmaker = key[4]
        current = by_prop.get(prop)
        if current is None or bookmaker < current[0]:
            by_prop[prop] = (bookmaker, samples)

    quotes: list[PropOddsQuote] = []
    for (row_league, _pkey, game_date, metric), (_book, samples) in by_prop.items():
        samples.sort(key=lambda item: item[0])
        opened = samples[0][1]
        closed = samples[-1][1]
        quotes.append(
            PropOddsQuote(
                league=row_league,
                player=opened["player"],
                game_date=game_date,
                market=metric,
                open_line=opened["line"],
                open_over_price=opened["over_odds"],
                open_under_price=opened["under_odds"],
                close_line=closed["line"],
                close_over_price=closed["over_odds"],
                close_under_price=closed["under_odds"],
                book=opened["book"],
            )
        )
    history = _index_quotes(quotes, source="odds_line_snapshots")
    history.skipped_rows = skipped
    return history


def _main_line_per_snapshot(
    samples: list[tuple[datetime, Mapping[str, Any]]],
) -> list[tuple[datetime, Mapping[str, Any]]]:
    """Keep the main line at each timestamp and drop the other rungs.

    ``bulk_props._main_book_line`` is the same picker the stored-snapshot
    reader uses. One timestamp with a ladder becomes one sample, so the
    earliest and latest samples are opens and closes rather than the
    ends of one book's alternate ladder.

    Args:
        samples: ``(snapshot_at, row)`` pairs for one bookmaker. Each row
            has ``line``, ``over_odds``, and ``under_odds``.

    Returns:
        One pair per distinct ``snapshot_at``, in the order those
        timestamps were first seen.
    """
    bootstrap()
    from app.services.bulk_props import _main_book_line

    by_time: dict[datetime, list[Mapping[str, Any]]] = {}
    order: list[datetime] = []
    for when, row in samples:
        if when not in by_time:
            order.append(when)
            by_time[when] = []
        by_time[when].append(row)
    collapsed: list[tuple[datetime, Mapping[str, Any]]] = []
    for when in order:
        chosen = _main_book_line([dict(row) for row in by_time[when]])
        collapsed.append((when, chosen))
    return collapsed


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).strip().replace("Z", "+00:00")
    return datetime.fromisoformat(text)
