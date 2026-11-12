"""Opponent defense ranks from the NBA game log.

Rank 1 is the most points allowed per game (the weakest defense). That
is the scale the picks page already documents: 1–10 Easy, 11–20 Average,
21–30 Hard. The only source is the game log (``csv``). A number that
arrived on an old row is not kept.

The lookup goes through ``canonical_team_code``. Some abbreviation sets
write ``GS``, ``NO``, ``NY``, ``SA``, ``PHO``, and ``UTAH``. The game
log and the lineup table use ``GSW``, ``NOP``, ``NYK``, ``SAS``,
``PHX``, and ``UTA``.

The season is the recorded current NBA season when the log has
regular-season games for it. Otherwise it is the latest season label
that does. A November slate whose CSV has not been refreshed yet still
gets a rank from the last season on file.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.services.game_log_hygiene import GAME_TYPE_REGULAR, coalesce_game_type
from app.services.nba_season import normalize_nba_season_label, recorded_nba_season_label

_POSITIONS = ("PG", "SG", "SF", "PF", "C")


@dataclass
class DefenseRankTable:
    """Ranks keyed by canonical team code. Position key is ``(code, POS)``."""

    season: str
    overall: dict[str, int] = field(default_factory=dict)
    by_position: dict[tuple[str, str], int] = field(default_factory=dict)


def _primary_position(value: Any) -> str:
    """First listed position token, or ``""`` when it is not a five-man spot."""
    text = str(value or "").strip().upper().replace("/", "-")
    token = text.split("-", 1)[0].strip()
    if token in _POSITIONS:
        return token
    return ""


def _game_day(game: dict[str, Any]) -> str:
    moment = game.get("game_date")
    if isinstance(moment, datetime):
        return moment.date().isoformat()
    text = str(game.get("date_full") or "").strip()
    return text[:10] if len(text) >= 10 else ""


def _team_code(name: Any) -> str:
    from app.services.daily_analysis import canonical_team_code

    return canonical_team_code(str(name or ""), league="nba")


def _counts_toward_points(game: dict[str, Any]) -> bool:
    """False for a zero-minute row. A row with no minutes field still counts.

    History already drops ``minutes == 0``. The shipped log's three
    zero-minute rows also have 0 points, so the totals do not move, but
    a later non-zero DNP must not enter the sum.
    """
    minutes = game.get("minutes")
    if minutes is None:
        return True
    if isinstance(minutes, (int, float)):
        return float(minutes) > 0
    text = str(minutes).strip()
    if text in {"", "0", "0.0", "0:00", "00:00"}:
        return False
    if ":" in text:
        parts = text.split(":", 1)
        try:
            return int(parts[0]) > 0 or int(parts[1]) > 0
        except (ValueError, IndexError):
            return True
    try:
        return float(text) > 0
    except ValueError:
        return True


_RANK_LIMIT = 30
CSV_RANK_SOURCE = "csv"
CSV_RANK_NOTE = "Computed from real points allowed, not fantasy points."

_EMPTY_RANK_FIELDS: dict[str, Any] = {
    "opponent_rank": None,
    "opponent_position_rank": None,
    "opponent_rank_source": None,
    "opponent_position_rank_source": None,
    "opponent_rank_season": None,
    "opponent_position_rank_season": None,
    "opponent_rank_note": None,
    "opponent_position_rank_note": None,
}


def _rank_descending(ppg: dict[str, float]) -> dict[str, int]:
    """1 = highest points allowed per game. Ties break by team code.

    Only the first 30 places are kept. A 31st opponent code does not
    become rank 31. Call this once per position, not on a map that
    mixes every team-position pair.
    """
    ordered = sorted(ppg.items(), key=lambda item: (-item[1], item[0]))
    ranked = {
        team: index
        for index, (team, _ppg) in enumerate(ordered, start=1)
        if index <= _RANK_LIMIT
    }
    return ranked


def build_defense_rank_table(games: list[dict[str, Any]]) -> DefenseRankTable:
    """Rank opponents from regular-season rows in one season.

    ``games`` are loaded game-log dicts (``team``, ``opponent``,
    ``points``, ``pos``, ``game_date``, ``season``, ``game_type``).
    A team's points on a date are the sum of its players' points. That
    sum is points allowed by the opponent.
    """
    regular = [
        game
        for game in games
        if coalesce_game_type(game.get("game_type")) == GAME_TYPE_REGULAR
    ]
    labels = {
        normalize_nba_season_label(str(game.get("season") or ""))
        for game in regular
        if str(game.get("season") or "").strip()
    }
    labels.discard("")
    current = recorded_nba_season_label()
    if current and current in labels:
        season = current
    elif labels:
        season = max(labels)
    else:
        season = current

    scoring: dict[tuple[str, str], float] = defaultdict(float)
    scoring_pos: dict[tuple[str, str, str], float] = defaultdict(float)
    opponents: dict[tuple[str, str], str] = {}
    for game in regular:
        if season and normalize_nba_season_label(str(game.get("season") or "")) != season:
            continue
        if not _counts_toward_points(game):
            continue
        team = _team_code(game.get("team"))
        opponent = _team_code(game.get("opponent"))
        day = _game_day(game)
        if not team or not opponent or not day:
            continue
        points = game.get("points")
        try:
            scored = float(points) if points is not None else 0.0
        except (TypeError, ValueError):
            scored = 0.0
        scoring[(team, day)] += scored
        position = _primary_position(game.get("pos"))
        if position:
            scoring_pos[(team, day, position)] += scored
        opponents[(team, day)] = opponent

    allowed: dict[str, list[float]] = defaultdict(list)
    allowed_pos: dict[tuple[str, str], list[float]] = defaultdict(list)
    for key, points in scoring.items():
        opponent = opponents.get(key)
        if not opponent:
            continue
        allowed[opponent].append(points)
        team, day = key
        for position in _POSITIONS:
            allowed_pos[(opponent, position)].append(
                scoring_pos.get((team, day, position), 0.0)
            )

    def _ppg(values: list[float]) -> float:
        return statistics.fmean(values) if values else 0.0

    overall = _rank_descending({team: _ppg(values) for team, values in allowed.items()})
    position_ranks: dict[tuple[str, str], int] = {}
    for position in _POSITIONS:
        subset = {
            team: _ppg(values)
            for (team, spot), values in allowed_pos.items()
            if spot == position
        }
        for team, rank in _rank_descending(subset).items():
            position_ranks[(team, position)] = rank
    return DefenseRankTable(season=season, overall=overall, by_position=position_ranks)


_TABLE_CACHE: dict[int, DefenseRankTable] = {}


def nba_defense_table() -> DefenseRankTable:
    """Rank table for the loaded NBA game log. Cached on the player-cache id."""
    from app.services.csv_player_history import csv_player_service

    csv_player_service.load_csv()
    cache_id = id(csv_player_service._cache)
    cached = _TABLE_CACHE.get(cache_id)
    if cached is not None:
        return cached
    games: list[dict[str, Any]] = []
    for rows in csv_player_service._cache.values():
        games.extend(rows)
    table = build_defense_rank_table(games)
    _TABLE_CACHE.clear()
    _TABLE_CACHE[cache_id] = table
    return table


def defense_fields(
    opponent: Any,
    position: Any,
    table: DefenseRankTable | None = None,
) -> dict[str, Any]:
    """Ranks for one opponent and position. Source is ``csv`` or null.

    ``opponent`` is canonicalized before the lookup, so ``GS`` and
    ``GSW`` hit the same row. An opponent that is not in the table, or
    a missing position, leaves that rank null. A number already stored
    on a caller is not an input here.

    Args:
        opponent: Team name or abbreviation. Empty when the club is unknown.
        position: Logged position. The first token must be PG, SG, SF, PF, or C.
        table: Rank table. None loads the NBA game log.

    Returns:
        The eight rank fields a ``DailyPick`` stores. Missing ranks are None.
    """
    if table is None:
        table = nba_defense_table()
    code = _team_code(opponent)
    spot = _primary_position(position)
    overall = table.overall.get(code) if code else None
    positional = table.by_position.get((code, spot)) if code and spot else None
    fields = dict(_EMPTY_RANK_FIELDS)
    if overall is not None:
        fields["opponent_rank"] = overall
        fields["opponent_rank_source"] = CSV_RANK_SOURCE
        fields["opponent_rank_season"] = table.season
        fields["opponent_rank_note"] = CSV_RANK_NOTE
    if positional is not None:
        fields["opponent_position_rank"] = positional
        fields["opponent_position_rank_source"] = CSV_RANK_SOURCE
        fields["opponent_position_rank_season"] = table.season
        fields["opponent_position_rank_note"] = CSV_RANK_NOTE
    return fields


def fill_null_defense_ranks(
    projection: dict[str, Any],
    table: DefenseRankTable | None = None,
) -> dict[str, Any]:
    """Copy ``projection`` and replace both ranks from the game log.

    ``opponent`` and ``position`` on the dict choose the row. Any
    ``opponent_rank`` already on the dict is ignored. An unknown
    opponent stays null.
    """
    updated = dict(projection)
    updated.update(
        defense_fields(
            projection.get("opponent"),
            projection.get("position"),
            table,
        )
    )
    return updated
