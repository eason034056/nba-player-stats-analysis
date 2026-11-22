"""
bdl_props_adapter.py - BALLDONTLIE player props to the Odds API bookmaker list.

``BdlPropsAdapter`` turns one ``/v2/odds/player_props`` ``data`` array into
the ``bookmakers`` list ``rows_from_bookmakers`` and ``_main_line_vote``
already read. The name is "adapter" because it changes the vendor's row
into that existing shape and does not fetch anything.

A row is one recorded object: ``vendor``, ``player_id``, ``prop_type``,
``line_value``, ``market`` (``type`` plus ``over_odds``/``under_odds`` or
``odds``), and ``updated_at``. Callers pass the display name for each
player id. This module does not invent a name, a price, or a book.
"""

from __future__ import annotations

import logging
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Vendors that may become a bookmaker.key. Anything else is dropped and
# counted. The keys are the ``vendor`` strings in the recorded props files.
VENDOR_TITLES: dict[str, str] = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "betmgm": "BetMGM",
    "caesars": "Caesars",
    "betrivers": "BetRivers",
    "fanatics": "Fanatics",
    "betparx": "BetParx",
    "ballybet": "Bally Bet",
    "betway": "Betway",
    "rebet": "Rebet",
}

# BetParx and Bally Bet post the same prices. They are one source, so they
# become one book before anyone votes. The surviving key is betparx when
# BetParx still has a row, otherwise ballybet. A book that posted nothing
# is not created.
PAIRED_VENDORS: frozenset[str] = frozenset({"betparx", "ballybet"})

# Frontend book key -> vendor string. The Odds API UI key for Bally Bet
# is ``bally_bet``. The recorded BALLDONTLIE vendor is ``ballybet``.
BOOK_KEY_ALIASES: dict[str, str] = {
    "bally_bet": "ballybet",
}

# prop_type -> Odds API market key. Blocks, triple-doubles, quarter
# props, and first-three-minute props are absent on purpose: they are
# not in SNAPSHOT_MARKETS.
PROP_TYPE_TO_MARKET: dict[str, str] = {
    "points": "player_points",
    "rebounds": "player_rebounds",
    "assists": "player_assists",
    "threes": "player_threes",
    "steals": "player_steals",
    "points_rebounds_assists": "player_points_rebounds_assists",
    "rebounds_assists": "player_rebounds_assists",
    "points_rebounds": "player_points_rebounds",
    "points_assists": "player_points_assists",
    "double_double": "player_double_double",
}

_DROPPED_PROP_SUFFIXES: tuple[str, ...] = ("_1q", "_first3min")


def _parse_utc(value: Any) -> datetime | None:
    """Parse one ISO timestamp. ``Z`` means UTC. Unusable values are None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _line_value(row: dict[str, Any]) -> float | None:
    """The posted total on one row, or None when ``line_value`` is not numeric."""
    try:
        return float(row.get("line_value"))
    except (TypeError, ValueError):
        return None


def normalize_book_keys(bookmakers: list[str] | None) -> set[str] | None:
    """Map a request's bookmaker filter onto vendor strings.

    ``None`` means no filter. ``bally_bet`` becomes ``ballybet``. Asking
    for either side of the BetParx / Bally Bet pair includes both, because
    they are one source and the fake-line rule needs both rows in view.
    """
    if bookmakers is None:
        return None
    selected: set[str] = set()
    for raw in bookmakers:
        if not isinstance(raw, str):
            continue
        key = raw.strip().lower()
        if not key:
            continue
        key = BOOK_KEY_ALIASES.get(key, key)
        selected.add(key)
    if selected & PAIRED_VENDORS:
        selected |= set(PAIRED_VENDORS)
    return selected


class BdlPropsAdapter:
    """Build an Odds API ``bookmakers`` list from BALLDONTLIE prop rows.

    Usage:
        books = BdlPropsAdapter().to_bookmakers(
            rows,
            names,
            game_datetime=tip,
            markets=("player_points",),
        )

    ``names`` maps a player id to the description string. An id that is
    missing from ``names`` is skipped. This class does not look the name
    up; ``BdlPlayerDirectory`` does that.

    After each ``to_bookmakers`` call the counters below describe that
    call only:

    - ``dropped_vendor_rows``: rows whose vendor is not on the allow-list
    - ``fake_points_dropped``: BetParx / Bally Bet points totals removed
      because they were not the anchored main
    - ``post_tip_dropped``: rows whose ``updated_at`` is after the tip
    - ``missing_name_rows``: rows skipped because ``names`` had no id
    """

    def __init__(self) -> None:
        self.dropped_vendor_rows: Counter[str] = Counter()
        self.fake_points_dropped = 0
        self.post_tip_dropped = 0
        self.missing_name_rows = 0
        self.last_player_ids: dict[str, int] = {}

    def to_bookmakers(
        self,
        rows: list[dict[str, Any]],
        names: dict[int, str],
        *,
        game_datetime: datetime | None = None,
        markets: tuple[str, ...] | None = None,
        bookmakers: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return the Odds API bookmaker list for these rows.

        Args:
            rows: ``response.data`` from ``/v2/odds/player_props``.
            names: Player id to the description the parsers store.
            game_datetime: Tip from the game's ``datetime``. Rows with
                ``updated_at`` strictly after this instant are in-game
                prices and are removed. ``None`` keeps every timestamp.
            markets: Market keys to keep. ``None`` keeps every mapped market.
            bookmakers: Vendor filter. ``None`` keeps the allow-list.
                ``bally_bet`` is read as ``ballybet``.

        Returns:
            Bookmaker dicts in allow-list order. A book with no remaining
            outcomes is omitted, so a milestone-only book such as Betway
            contributes no vote.
        """
        self.dropped_vendor_rows = Counter()
        self.fake_points_dropped = 0
        self.post_tip_dropped = 0
        self.missing_name_rows = 0
        self.last_player_ids = {}

        wanted_markets = set(markets) if markets is not None else None
        wanted_books = normalize_book_keys(bookmakers)
        tip = _as_utc(game_datetime)
        kept = self._select_rows(rows, wanted_books=wanted_books, tip=tip)

        # book key -> market key -> outcomes, plus the latest source timestamp
        outcomes: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        last_update: dict[tuple[str, str], str] = {}
        player_ids: dict[str, int] = {}

        for row in kept:
            built = self._outcomes_for_row(row, names)
            if built is None:
                continue
            market_key, row_outcomes, updated = built
            if wanted_markets is not None and market_key not in wanted_markets:
                continue
            book_key = self._book_key(row, kept)
            bucket = outcomes[book_key][market_key]
            bucket.extend(row_outcomes)
            previous = last_update.get((book_key, market_key))
            if updated and (previous is None or updated > previous):
                last_update[(book_key, market_key)] = updated
            player_id = row.get("player_id")
            for outcome in row_outcomes:
                description = outcome.get("description")
                if isinstance(description, str) and isinstance(player_id, int):
                    player_ids[description] = player_id

        self.last_player_ids = player_ids
        return self._assemble(outcomes, last_update)

    def _select_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        wanted_books: set[str] | None,
        tip: datetime | None,
    ) -> list[dict[str, Any]]:
        """Apply the allow-list, the tip cutoff, and the fake-line drop."""
        selected: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            vendor = row.get("vendor")
            if not isinstance(vendor, str) or vendor not in VENDOR_TITLES:
                if isinstance(vendor, str) and vendor:
                    self.dropped_vendor_rows[vendor] += 1
                continue
            if wanted_books is not None and vendor not in wanted_books:
                continue
            updated = _parse_utc(row.get("updated_at"))
            if tip is not None and updated is not None and updated > tip:
                self.post_tip_dropped += 1
                continue
            selected.append(row)

        if self.dropped_vendor_rows:
            for vendor, count in sorted(self.dropped_vendor_rows.items()):
                logger.info("bdl_vendor_dropped vendor=%s rows=%s", vendor, count)

        return self._drop_fake_low_points(selected)

    def _drop_fake_low_points(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep one points total for the BetParx / Bally Bet pair.

        Scope is ``prop_type == "points"`` over/under rows on that pair.
        A player with one pair total is unchanged. Other vendors' rows are
        not dropped here. The pair still collapses to one book afterwards.

        When the pair has two or more distinct totals for one player:

        1. ``other_mains`` is one numeric line per other allow-listed vendor
           that posted a single points total for that player. A vendor with
           two or more distinct totals is omitted. Its main is ambiguous.
        2. If ``other_mains`` is non-empty, the consensus is the median of
           those lines. An even count averages the two middle values. The
           pair keeps the candidate closest to that median. A distance tie
           keeps the candidate the other books posted more often, then the
           lower total. Every other pair total for that player is dropped,
           from both vendors.
        3. If ``other_mains`` is empty, the pair keeps ``max(lines)``. With
           no other book, a shared low total plus a higher singleton has
           the same shape as a shared main plus a higher alternate, so
           there is no signal that beats the maximum. The maximum still
           drops the recorded isolated-low fake.

        The snapshot parser stores every two-sided rung, so the rejected
        total has to be gone before ``to_bookmakers`` returns.
        """
        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if row.get("vendor") not in PAIRED_VENDORS:
                continue
            if row.get("prop_type") != "points":
                continue
            market = row.get("market")
            if not isinstance(market, dict) or market.get("type") != "over_under":
                continue
            player_id = row.get("player_id")
            if isinstance(player_id, int):
                grouped[player_id].append(row)

        drop_ids: set[int] = set()
        for player_id, player_rows in grouped.items():
            lines = [line for line in (_line_value(row) for row in player_rows) if line is not None]
            distinct = set(lines)
            if len(distinct) < 2:
                continue
            keep = _choose_pair_total(distinct, _other_points_mains(rows, player_id))
            for row in player_rows:
                line = _line_value(row)
                row_id = row.get("id")
                if line is None or line != keep:
                    if isinstance(row_id, int):
                        drop_ids.add(row_id)

        if not drop_ids:
            return rows
        kept: list[dict[str, Any]] = []
        for row in rows:
            row_id = row.get("id")
            if isinstance(row_id, int) and row_id in drop_ids:
                self.fake_points_dropped += 1
                continue
            kept.append(row)
        return kept

    def _book_key(self, row: dict[str, Any], kept: list[dict[str, Any]]) -> str:
        """Vendor key, with the BetParx / Bally Bet pair collapsed to one book.

        The key is ``betparx`` when any surviving row is BetParx. It is
        ``ballybet`` only when Bally Bet is the only side of the pair that
        still has a row. That does not invent a book: the key is a vendor
        that posted something we kept.
        """
        vendor = str(row.get("vendor"))
        if vendor not in PAIRED_VENDORS:
            return vendor
        for other in kept:
            if other.get("vendor") == "betparx":
                return "betparx"
        return "ballybet"

    def _outcomes_for_row(
        self,
        row: dict[str, Any],
        names: dict[int, str],
    ) -> tuple[str, list[dict[str, Any]], str] | None:
        """One row to ``(market key, outcomes, updated_at)``, or None to skip."""
        prop_type = row.get("prop_type")
        if not isinstance(prop_type, str):
            return None
        if prop_type.endswith(_DROPPED_PROP_SUFFIXES):
            return None
        market_key = PROP_TYPE_TO_MARKET.get(prop_type)
        if market_key is None:
            return None
        market = row.get("market")
        if not isinstance(market, dict):
            return None
        player_id = row.get("player_id")
        if not isinstance(player_id, int):
            self.missing_name_rows += 1
            return None
        description = names.get(player_id)
        if not isinstance(description, str) or not description.strip():
            self.missing_name_rows += 1
            return None
        description = description.strip()
        updated = row.get("updated_at") if isinstance(row.get("updated_at"), str) else ""
        market_type = market.get("type")

        if market_key == "player_double_double":
            # Double-double is a Yes price. Other milestones are alt lines
            # and are not copied. There is no No price in the recorded rows,
            # so none is added.
            if market_type != "milestone":
                return None
            price = _american(market.get("odds"))
            if price is None:
                return None
            return (
                market_key,
                [{"name": "Yes", "description": description, "price": price}],
                updated,
            )

        if market_type != "over_under":
            return None
        point = _line_value(row)
        if point is None:
            return None
        outcomes: list[dict[str, Any]] = []
        over = _american(market.get("over_odds"))
        under = _american(market.get("under_odds"))
        if over is not None:
            outcomes.append(
                {
                    "name": "Over",
                    "description": description,
                    "price": over,
                    "point": point,
                }
            )
        if under is not None:
            outcomes.append(
                {
                    "name": "Under",
                    "description": description,
                    "price": under,
                    "point": point,
                }
            )
        if not outcomes:
            return None
        return market_key, outcomes, updated

    def _assemble(
        self,
        outcomes: dict[str, dict[str, list[dict[str, Any]]]],
        last_update: dict[tuple[str, str], str],
    ) -> list[dict[str, Any]]:
        """Allow-list order. Books and markets with no outcomes are left out."""
        books: list[dict[str, Any]] = []
        for key in VENDOR_TITLES:
            markets_for_book = outcomes.get(key)
            if not markets_for_book:
                continue
            markets: list[dict[str, Any]] = []
            for market_key, market_outcomes in markets_for_book.items():
                if not market_outcomes:
                    continue
                market: dict[str, Any] = {
                    "key": market_key,
                    "outcomes": market_outcomes,
                }
                updated = last_update.get((key, market_key))
                if updated:
                    market["last_update"] = updated
                markets.append(market)
            if not markets:
                continue
            books.append(
                {
                    "key": key,
                    "title": VENDOR_TITLES[key],
                    "markets": markets,
                }
            )
        return books


def _as_utc(moment: datetime | None) -> datetime | None:
    """Naive datetimes are UTC. Aware datetimes are converted to UTC."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _american(value: Any) -> int | None:
    """American price as an int, or None when the field is missing or zero.

    A recorded price is a whole number. Zero is not a posted price.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    price = int(value)
    if price == 0:
        return None
    return price


def _other_points_mains(rows: list[dict[str, Any]], player_id: int) -> list[float]:
    """One points total per non-paired vendor, skipping an ambiguous vendor.

    A vendor that posted two or more distinct over/under totals for this
    player is left out. This rule does not guess which of those totals
    is the book's main.
    """
    by_vendor: dict[str, set[float]] = defaultdict(set)
    for row in rows:
        vendor = row.get("vendor")
        if not isinstance(vendor, str) or vendor in PAIRED_VENDORS or vendor not in VENDOR_TITLES:
            continue
        if row.get("prop_type") != "points" or row.get("player_id") != player_id:
            continue
        market = row.get("market")
        if not isinstance(market, dict) or market.get("type") != "over_under":
            continue
        line = _line_value(row)
        if line is not None:
            by_vendor[vendor].add(line)
    mains: list[float] = []
    for lines in by_vendor.values():
        if len(lines) == 1:
            mains.append(next(iter(lines)))
    return mains


def _choose_pair_total(candidates: set[float], other_mains: list[float]) -> float:
    """The pair total to keep for one player.

    With other books, keep the candidate closest to their median. Ties
    prefer the total those books posted more often, then the lower total.
    With no other main, keep the highest candidate.
    """
    if not other_mains:
        return max(candidates)
    consensus = float(statistics.median(other_mains))
    counts = Counter(other_mains)

    def rank(line: float) -> tuple[float, int, float]:
        return (abs(line - consensus), -counts[line], line)

    return min(candidates, key=rank)


def consensus_lines(books: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    """One consensus total per player and market.

    The vote is ``DailyAnalysisService._group_main_votes`` plus
    ``calculate_mode_threshold``, one market at a time.
    ``player_double_double`` has no total, so it is not a key. The
    same-slate test and ``scripts/record_bdl_odds_fixtures.py`` both call
    this function so the definition cannot drift.
    """
    from app.services.daily_analysis import DailyAnalysisService
    from app.services.prob import calculate_mode_threshold

    service = DailyAnalysisService()
    keys: list[str] = []
    for book in books:
        if not isinstance(book, dict):
            continue
        for market in book.get("markets") or []:
            if not isinstance(market, dict):
                continue
            key = market.get("key")
            if isinstance(key, str) and key not in keys and key != "player_double_double":
                keys.append(key)
    found: dict[tuple[str, str], float] = {}
    for key in keys:
        sliced: list[dict[str, Any]] = []
        for book in books:
            if not isinstance(book, dict):
                continue
            markets = [
                item
                for item in (book.get("markets") or [])
                if isinstance(item, dict) and item.get("key") == key
            ]
            if markets:
                sliced.append({**book, "markets": markets})
        votes = service._group_main_votes(sliced)
        for player, pairs in votes.items():
            lines = [line for line, _distance in pairs]
            distances = [distance for _line, distance in pairs]
            mode = calculate_mode_threshold(lines, distances)
            if mode is not None:
                found[(str(player), key)] = float(mode)
    return found
