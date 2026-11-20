"""
bdl_stats.py - normalize BALLDONTLIE ``GET /v1/stats`` rows.

The spellings handled here are the ones in the SPO-138a captures
(``backend/tests/fixtures/bdl/stats__*.json``) and the full 2000-01 to
2026-27 walk that found the later ones.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

_MINUTES = re.compile(r"(\d{1,3})(?::([0-5]\d|60))?")

BOX_STATS: tuple[str, ...] = (
    "pts", "reb", "ast", "stl", "blk", "turnover", "pf",
    "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb",
)
SHOOTING_PCTS: tuple[str, ...] = ("fg_pct", "fg3_pct", "ft_pct")
_ATTEMPTED_BY_PCT = {"fg_pct": "fga", "fg3_pct": "fg3a", "ft_pct": "fta"}

Fraction = Annotated[float, Field(ge=0, le=1)]


class BdlStatRowError(ValueError):
    """One ``/v1/stats`` row that cannot be normalized.

    The caller skips and counts the row. One bad row does not stop a season.
    """


class BdlStatLine(BaseModel):
    """One player's line for one game, in the same shape for every season.

    A did-not-play row has ``dnp=True`` and every stat, ``plus_minus``, and
    ``seconds_played`` set to ``None``, whichever way the season spelled it.
    ``team_id`` is the team that played the game. ``player.team_id`` in the
    raw row is the player's team today and is not read.
    Shooting percentages are 0-1 fractions as BALLDONTLIE rounds them, and
    ``None`` when the player took no attempt, which several seasons send
    as 0. A percentage over several games is total made over total
    attempted, not the mean of these. The 2019-20 to 2021-22 play-in games
    send them on a 0-100 scale (``66.7`` for 4 of 6); those are divided by 100.
    """

    model_config = ConfigDict(frozen=True)

    stat_id: int
    game_id: int
    player_id: int
    team_id: int
    dnp: bool
    seconds_played: int | None
    pts: int | None
    reb: int | None
    ast: int | None
    stl: int | None
    blk: int | None
    turnover: int | None
    pf: int | None
    fgm: int | None
    fga: int | None
    fg3m: int | None
    fg3a: int | None
    ftm: int | None
    fta: int | None
    oreb: int | None
    dreb: int | None
    fg_pct: Fraction | None
    fg3_pct: Fraction | None
    ft_pct: Fraction | None
    plus_minus: int | None


def parse_minutes(raw: object) -> int | None:
    """Return BALLDONTLIE ``min`` as seconds played.

    ``"16"`` is 960 and ``"13:44"`` is 824. The 2000-01 capture mixes both
    spellings on one page; the 2025-26 capture has whole minutes only.
    ``"28:60"`` is 29:00: the full 2000-01 walk has 19 such rows, every one
    a player who played (``stats__season2000_cursor272160_page.json``).
    ``None`` or ``""`` means the row has no minutes and returns ``None``.

    Raises:
        BdlStatRowError: for any other value, so a new spelling is seen
            instead of being read as a wrong number.
    """
    if raw is None or raw == "":
        return None
    match = _MINUTES.fullmatch(raw) if isinstance(raw, str) else None
    if match is None:
        raise BdlStatRowError(f"unrecognized minutes value {raw!r}")
    minutes, seconds = match.groups()
    return int(minutes) * 60 + int(seconds or 0)


def _percentage(value: Any, attempted: Any) -> Any:
    """``None`` for a shot type never taken; a value over 1 is on the 0-100 scale.

    A single-game share under 1% is not possible, so a value over 1 cannot
    be a fraction.
    """
    if attempted == 0:
        return None
    if isinstance(value, int | float) and value > 1:
        return round(value / 100, 3)
    return value


def normalize_stat_row(row: dict[str, Any]) -> BdlStatLine:
    """Turn one raw ``/v1/stats`` row into a ``BdlStatLine``.

    A row is did-not-play when nothing in it shows court time: no seconds
    (``min`` null or zero), every box stat zero or null, and ``plus_minus``
    zero or null. The percentages are cleared with the rest, a 0 included.
    BALLDONTLIE has spelled that four ways:

    - 2000-01: ``min: null`` with null stats.
    - 2025-26 until 2025-12-22: ``min: "00"`` with zeros and ``plus_minus: null``.
    - 2025-26 from 2025-12-23: the same with ``plus_minus: 0``
      (``stats__season2025_cursor24626559_page.json`` has both). Read as
      played, these made 30.5 players a game against about 21 in every
      other season.
    - 2026-27: ``min: "0"`` with zeros and ``plus_minus: 0``.

    BALLDONTLIE also added 21 rows with ``min: null``, zeros, and
    ``plus_minus: 0`` to 2025-26 later; every team they belong to already
    has its 240 minutes without them.

    A player on court for a few seconds who recorded nothing and left with
    the score level is spelled the same way and also reads as did-not-play
    (28 to 62 rows a season in 2019-20 to 2024-25). A nonzero
    ``plus_minus`` or any stat with ``"0"`` minutes is under a minute played.

    Raises:
        BdlStatRowError: when a field is missing, a value has the wrong
            type, or the row has stats but no minutes.
    """
    try:
        seconds = parse_minutes(row["min"])
        box = {name: row[name] for name in BOX_STATS}
        pcts = {name: _percentage(row[name], box[_ATTEMPTED_BY_PCT[name]]) for name in SHOOTING_PCTS}
        plus_minus = row["plus_minus"]
        ids = {
            "stat_id": row["id"],
            "game_id": row["game"]["id"],
            "player_id": row["player"]["id"],
            "team_id": row["team"]["id"],
        }
    except (KeyError, TypeError) as exc:
        raise BdlStatRowError(f"stats row {row.get('id')!r} is missing {exc}") from exc

    on_court = bool(seconds) or any(box.values()) or bool(plus_minus)
    if not on_court:
        values: dict[str, Any] = dict.fromkeys((*BOX_STATS, *SHOOTING_PCTS, "plus_minus", "seconds_played"))
        dnp = True
    elif seconds is None:
        raise BdlStatRowError(f"stats row {row['id']!r} has stats but no minutes")
    else:
        values = {**box, **pcts, "plus_minus": plus_minus, "seconds_played": seconds}
        dnp = False

    try:
        return BdlStatLine(**ids, dnp=dnp, **values)
    except ValidationError as exc:
        raise BdlStatRowError(f"stats row {row['id']!r} has an invalid value") from exc
