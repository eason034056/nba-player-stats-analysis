"""Opening game-odds features at the same T as the rest of the row.

Only ``snapshot_kind = 'opening'`` rows with a non-NULL ``snapshot_at`` at
or before T are used. Closing and live rows are ignored. A NULL timestamp
is ignored, not filled in. T comes from :func:`app.ml.asof.prediction_instant`.
This module does not subtract ``hours_before_tip`` again.

For the books that remain, the features are the median ``spread_home_value``
and the median ``total_value``. NULL values are skipped per column. The
player's team and the opponent then get implied points::

    total / 2 - team_spread / 2

Home uses the median home spread. Away uses that spread's negation.
Home -4 and total 220 is 112 for the home team and 108 for the away team.
No eligible value stays NULL. It is not stored as zero. A spread of 0 is a
real line and is kept.

One player-game stays one row. Books are aggregated, not joined onto the
row. Counts record how many books were eligible and how many supplied each
number. The count of books is whatever the table holds for that game. It
is not a fixed one-book or twelve-book assumption.

An opening row is not an immutable first post. The unique key is one row
per game and book, and a retry may change ``snapshot_at`` and the values.
``snapshot_at`` is when BDL says the line opened. A historical import shows
that BDL published the value then. It does not show that this application
observed it then.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.ml.load import GameOddsRecord
from app.ml.sources import opening_game_odds_visible

# Value columns are NULL when that metric has no eligible number.
# Count columns are 0 in that case: 0 is the coverage, not a filled line.
ODDS_VALUE_COLUMNS = (
    "opening_spread_home",
    "opening_total",
    "team_implied_points",
    "opp_implied_points",
)
ODDS_COUNT_COLUMNS = (
    "opening_books",
    "opening_spread_books",
    "opening_total_books",
)
ODDS_COLUMNS = ODDS_VALUE_COLUMNS + ODDS_COUNT_COLUMNS

MEASUREMENT_STATUS = "PENDING"
MEASUREMENT_SQL = "docs/decisions/SPO-138/game-odds-opener-timing.sql"
OPENING_ODDS_LIMITATION = (
    "An opening game_odds_snapshots row is one per game and book. "
    "snapshot_at is BDL opened_at and is not part of the unique key, so a retry "
    "can change the timestamp and the values. The row is not an immutable "
    "first-observed history. A historical import shows that BDL published a "
    "value at opened_at. It does not show that this application polled that "
    "value at opened_at. Opener timing against a real tip has not been measured "
    "on the database; see the PENDING note and the SQL file. Prop openers are "
    "not assumed to sit on the same boundary."
)


class GameOddsError(ValueError):
    """Opening odds for one game cannot be aggregated."""


def median_value(values: Sequence[float]) -> float | None:
    """Return the middle value, or None when ``values`` is empty.

    An odd count uses the middle value after sorting. An even count uses
    the mean of the two middle values. An empty sequence is None, not zero.
    The caller has already dropped NULL inputs.

    Args:
        values: Non-null numbers, in any order.

    Returns:
        The median, or None when there is nothing to aggregate.
    """
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return float(ordered[mid - 1] + ordered[mid]) / 2


def implied_team_points(total: float, team_spread: float) -> float:
    """Return ``total / 2 - team_spread / 2`` for one side of the game.

    Args:
        total: Median game total.
        team_spread: That side's spread. Home uses the median home spread.
            Away uses the negation of the median home spread. A negative
            spread means that side is favored and is assigned more than
            half of the total.

    Returns:
        Implied points for ``team_spread``'s side. Home -4 and total 220
        returns 112 for the home side.
    """
    return total / 2 - team_spread / 2


def opening_odds_features(
    rows: Sequence[GameOddsRecord],
    *,
    league: str,
    bdl_game_id: int,
    is_home: bool | None,
    as_of: datetime,
) -> dict[str, object]:
    """Aggregate opening lines for one player-game.

    ``rows`` may include other games, other leagues, closing or live rows,
    NULL timestamps, and rows after ``as_of``. Those rows are ignored.
    ``as_of`` is the row's T. This function does not compute another cutoff.

    Args:
        rows: Odds records, already loaded or built in memory.
        league: League of the player-game.
        bdl_game_id: Game of the player-game.
        is_home: True when the player's team is the home team, False when
            it is the away team, None when the home team is unknown.
            None leaves both implied-point features NULL.
        as_of: T for this game, timezone-aware.

    Returns:
        The median spread and total, both sides' implied points, and the
        book counts. Value features are NULL when that metric has no
        eligible number. Counts are integers, including 0.

    Raises:
        GameOddsError: two visible opening rows share a book. The opening
            key is one row per game and book, so a second visible row would
            count that book twice.
        SourceError: a visible timestamp has no timezone.
    """
    eligible: list[GameOddsRecord] = []
    for row in rows:
        if row.league != league or row.bdl_game_id != bdl_game_id:
            continue
        if not opening_game_odds_visible(
            snapshot_kind=row.snapshot_kind,
            snapshot_at=row.snapshot_at,
            as_of=as_of,
        ):
            continue
        eligible.append(row)

    seen: set[str] = set()
    for row in eligible:
        if row.book_key in seen:
            raise GameOddsError(
                f"duplicate opening book {row.book_key} for game {bdl_game_id}"
            )
        seen.add(row.book_key)

    spreads = [row.spread_home_value for row in eligible if row.spread_home_value is not None]
    totals = [row.total_value for row in eligible if row.total_value is not None]
    spread = median_value(spreads)
    total = median_value(totals)
    team_points: float | None = None
    opp_points: float | None = None
    if spread is not None and total is not None and is_home is not None:
        team_spread = spread if is_home else -spread
        team_points = implied_team_points(total, team_spread)
        opp_points = implied_team_points(total, -team_spread)

    return {
        "opening_spread_home": spread,
        "opening_total": total,
        "team_implied_points": team_points,
        "opp_implied_points": opp_points,
        "opening_books": len(eligible),
        "opening_spread_books": len(spreads),
        "opening_total_books": len(totals),
    }
