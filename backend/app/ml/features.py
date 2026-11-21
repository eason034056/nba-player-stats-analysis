"""Player-form features from games strictly before the target date.

Played-game windows (``dnp`` false) are the last 5 and last 10 games for
``pts``, ``reb``, ``ast``, ``fg3m``, ``stl``, ``blk``, and ``seconds_played``.
A window that is not full is NULL. The count of played games is kept beside
it. A missing game is never filled with zero.

``dnp_last_10`` is a different window: the last 10 prior player rows, DNP
and played together, ordered by date then ``bdl_game_id``. It counts how
many of those rows are DNP. ``dnp_last_10_window`` is how many rows that
count used (at most 10). It is not the number of DNPs inside the last 10
played games.

``days_rest`` is the number of calendar days since the previous player row,
DNP included. The windows may cross seasons. The caller passes earlier
seasons in ``history``; this function does not drop them.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.ml.load import GameRecord, StatRecord
from app.ml.sources import require_feature_source, row_is_visible

FORM_STATS = ("pts", "reb", "ast", "fg3m", "stl", "blk", "seconds_played")
PLAYED_WINDOWS = (5, 10)
DNP_ROW_WINDOW = 10

# Counts and rest. ``is_home`` and ``season_type`` are schedule columns on the
# target row, so they are not repeated here.
COUNT_COLUMNS = (
    "n_prev_games",
    "n_played_prev",
    "dnp_last_10",
    "dnp_last_10_window",
    "days_rest",
    "is_back_to_back",
)


def form_column_names() -> tuple[str, ...]:
    """Column names of the played-game means, last-5 then last-10 per stat."""
    names: list[str] = []
    for window in PLAYED_WINDOWS:
        for stat in FORM_STATS:
            names.append(f"{stat}_last_{window}")
    return tuple(names)


def _mean(rows: Sequence[StatRecord], stat: str) -> float | None:
    total = 0
    for row in rows:
        value = getattr(row, stat)
        if value is None:
            return None
        total += value
    return total / len(rows)


def _is_home(target: StatRecord, game: GameRecord) -> bool | None:
    if game.home_team_id is None:
        return None
    return target.bdl_team_id == game.home_team_id


def features_for_target(
    history: Sequence[StatRecord],
    target: StatRecord,
    game: GameRecord,
) -> dict[str, object]:
    """Form features for one player-game.

    ``history`` may be in any order and may include the target, a later
    game, and an earlier game on the target's date. Those rows are ignored.
    Only rows that pass the ``player_game_stats`` prior-date rule are used.

    Args:
        history: Stat rows for this player, including other seasons.
        target: The player-game the row is about.
        game: That game's schedule row (home team and ``season_type``).

    Returns:
        Identity columns, context columns, and the played-game means.
        Means are NULL when the played window is shorter than 5 or 10, or
        when a stat in an otherwise full window is NULL.
    """
    spec = require_feature_source("player_game_stats")
    ordered = sorted(
        (
            row
            for row in history
            if row.league == target.league and row.bdl_player_id == target.bdl_player_id
        ),
        key=lambda row: (row.game_date, row.bdl_game_id),
    )
    prior = [
        row
        for row in ordered
        if row_is_visible(
            spec.visibility,
            observed_at=None,
            row_date=row.game_date,
            target_date=target.game_date,
            as_of=None,
        )
    ]
    played = [row for row in prior if not row.dnp]
    dnp_rows = prior[-DNP_ROW_WINDOW:]
    if prior:
        days_rest: int | None = (target.game_date - prior[-1].game_date).days
        back_to_back: bool | None = days_rest == 1
    else:
        days_rest = None
        back_to_back = None

    values: dict[str, object] = {
        "league": target.league,
        "season": target.season,
        "date": target.game_date,
        "bdl_game_id": target.bdl_game_id,
        "bdl_player_id": target.bdl_player_id,
        "bdl_team_id": target.bdl_team_id,
        "season_type": game.season_type,
        "is_home": _is_home(target, game),
        "n_prev_games": len(prior),
        "n_played_prev": len(played),
        "dnp_last_10": sum(1 for row in dnp_rows if row.dnp),
        "dnp_last_10_window": len(dnp_rows),
        "days_rest": days_rest,
        "is_back_to_back": back_to_back,
    }
    for window in PLAYED_WINDOWS:
        sample = played[-window:] if len(played) >= window else None
        for stat in FORM_STATS:
            values[f"{stat}_last_{window}"] = None if sample is None else _mean(sample, stat)
    return values
