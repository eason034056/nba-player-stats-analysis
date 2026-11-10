"""No-lookahead opponent defense ranks from a game-log cache.

Rank 1 allowed the most of that stat in games dated strictly before the
target date. That is the weak end, the same direction ``DailyPick`` stores:
SportsDataIO's ``OpponentRank`` is copied through with no inversion, and
the schema says 1 = weakest defense.

This is a replay proxy. It is not the SportsDataIO fantasy-points rank.
Position rank is preferred when the target player's position has enough
prior player-games against that opponent. Otherwise the overall rank is
used. Below the sample floor the rank is missing.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Callable

# Player-games against one opponent before a rank is published.
MIN_OVERALL_GAMES = 20
MIN_POSITION_GAMES = 8


class DefenseRankIndex:
    """Ranks snapped at each date, using only games before that date."""

    def __init__(
        self,
        snapshots: dict[datetime, dict[str, dict[tuple, int]]],
    ):
        self._dates = sorted(snapshots)
        self._snapshots = snapshots

    def rank(
        self,
        game_date: datetime,
        opponent: str,
        metric: str,
        position: str | None,
    ) -> int | None:
        """Position rank when it exists, otherwise the overall rank.

        Args:
            game_date: Target date. Games on this date are not in the rank.
            opponent: Opponent label, matched exactly to the CSV ``Opponent``.
            metric: CSV metric key (``points``, ``rebounds``, …).
            position: Player position such as ``PG``. Blank skips the position rank.

        Returns:
            Rank starting at 1 for the most permissive defense, or None.
        """
        snap = self._snapshot_for(game_date)
        if snap is None or not opponent:
            return None
        if position:
            position_rank = snap["position"].get((metric, position, opponent))
            if position_rank is not None:
                return position_rank
        return snap["overall"].get((metric, opponent))

    def _snapshot_for(self, game_date: datetime) -> dict | None:
        if game_date in self._snapshots:
            return self._snapshots[game_date]
        previous = None
        for date in self._dates:
            if date >= game_date:
                break
            previous = date
        if previous is None:
            return None
        return self._snapshots[previous]

    @classmethod
    def from_cache(
        cls,
        cache: dict,
        metrics: list[str],
        extractors: dict[str, Callable],
    ) -> "DefenseRankIndex":
        """Build ranks from a player → game-log cache.

        ``cache`` values are the lists ``CSVPlayerHistoryService`` stores.
        Only games with minutes and a date contribute. Same-day games are
        excluded from that day's snapshot, matching the walk-forward rule
        that a prior game must be dated strictly before the target.
        """
        rows: list[tuple[datetime, str, str, dict[str, float]]] = []
        for logs in cache.values():
            for game in logs:
                game_date = game.get("game_date")
                if game_date is None or (game.get("minutes") or 0) <= 0:
                    continue
                values: dict[str, float] = {}
                for metric in metrics:
                    extractor = extractors.get(metric)
                    if extractor is None:
                        continue
                    value = extractor(game)
                    if value is None:
                        continue
                    values[metric] = float(value)
                if not values:
                    continue
                rows.append(
                    (
                        game_date,
                        str(game.get("opponent") or ""),
                        str(game.get("pos") or "").strip(),
                        values,
                    )
                )
        rows.sort(key=lambda row: row[0])

        overall_sum: dict[tuple[str, str], list[float]] = defaultdict(
            lambda: [0.0, 0.0]
        )
        position_sum: dict[tuple[str, str, str], list[float]] = defaultdict(
            lambda: [0.0, 0.0]
        )
        snapshots: dict[datetime, dict[str, dict[tuple, int]]] = {}
        index = 0
        while index < len(rows):
            date = rows[index][0]
            snapshots[date] = {
                "overall": _assign_ranks(overall_sum, MIN_OVERALL_GAMES, 1),
                "position": _assign_ranks(position_sum, MIN_POSITION_GAMES, 2),
            }
            while index < len(rows) and rows[index][0] == date:
                _opponent, _position, values = rows[index][1], rows[index][2], rows[index][3]
                if _opponent:
                    for metric, value in values.items():
                        cell = overall_sum[(metric, _opponent)]
                        cell[0] += value
                        cell[1] += 1.0
                        if _position:
                            positioned = position_sum[(metric, _position, _opponent)]
                            positioned[0] += value
                            positioned[1] += 1.0
                index += 1
        return cls(snapshots)


def _assign_ranks(
    totals: dict[tuple, list[float]], minimum: int, opponent_index: int
) -> dict[tuple, int]:
    """Highest mean allowed gets rank 1. Ties break by opponent name.

    ``opponent_index`` is the tuple slot that holds the opponent label.
    Groups that share every slot except the opponent are ranked together,
    so overall ranks are per metric and position ranks are per metric and
    position.
    """
    grouped: dict[tuple, list[tuple[float, str, tuple]]] = defaultdict(list)
    for key, (total, count) in totals.items():
        if count < minimum:
            continue
        group = tuple(part for index, part in enumerate(key) if index != opponent_index)
        opponent = key[opponent_index]
        grouped[group].append((-(total / count), str(opponent), key))
    ranks: dict[tuple, int] = {}
    for items in grouped.values():
        items.sort()
        for rank, (_mean, _opponent, key) in enumerate(items, start=1):
            ranks[key] = rank
    return ranks
