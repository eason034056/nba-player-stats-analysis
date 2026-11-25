"""Teammate absence, starter stand-in, and the player's own injury status.

NBA only. These columns are filled on an NBA row. This module does not
grow a second league.

``team_absences`` is the one function for a training row and for a live
read. The live caller passes the narrow bundle from
:func:`app.ml.load.load_team_absence_inputs`. The training caller may pass
that same shape, or every stat it has already loaded. Both paths apply one
cutoff: the ``as_of`` argument, which is :func:`app.ml.asof.prediction_instant`
and is not recomputed here.

A rotation player, for one team and one target game:

- his latest game dated before the target was for this team
- he played at least 3 of this team's last 10 games dated before the target
- in the games he played among those 10, his average was at least 15 minutes

Exactly 3 games and exactly 15:00 qualify. 2 games or 14:59 do not. A game
on the target date does not count. A player whose latest earlier game is
for another team is not this team's rotation player.

``source='actual'`` is the box-score stand-in. A rotation player with no
row in the target game, or with a DNP row, has ``p_out`` 1. A player who
played is not absent. Using this source makes the dataset row
``info_source='standin'``.

``source='reported'`` reads ``injury_snapshots`` when the caller does not
pass official report rows. The newest row with ``snapshot_at <= T`` is
kept, and it counts only when that row is still ``listed``. A newer
``listed = false`` row at or before T removes the player. That is the same
order as ``current_injuries``. The starting scale is Out 1, Doubtful 0.75,
Questionable 0.5, Day-To-Day 0.25, Probable 0.1. An unknown word or a blank
status is not given a probability. It is counted and the player is left out
of the absence list.

Official ``nba_injury_report_rows`` replace that snapshot list for the same
``source='reported'`` path. The rows are already matched or left unmatched.
This module does not match names. For one game it keeps the latest report
with ``report_at <= T``, and it ignores every other ``bdl_game_id``.
``Available`` has ``p_out`` 0 on that path only. The other weights stay on
the scale above. Numbers are written only when a complete
``injuries_nba_official`` refresh covers T (the 90-minute
``source_covered`` rule). No such report leaves the absence columns NULL
and sets ``injury_report_missing`` to 1.

Minutes and shares use earlier games only. They are weighted by ``p_out``.
The row's own player is left out of his team's totals. He is not left out
of the opponent's totals.

When injury coverage is unknown, a pregame row does not store 0 for those
features. An empty report is not evidence that everyone is healthy.
``source_covered`` is not on this branch, so the export records coverage as
unknown. ``source='actual'`` may still store numbers, and those rows are
``standin``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.ml.labels import CATALOG_MARKETS
from app.ml.load import (
    InjuryRecord,
    LineupRecord,
    OfficialRefresh,
    OfficialReportRow,
    ProjectedStarterRow,
    StatRecord,
)
from app.services.injury_status import (
    DAY_TO_DAY,
    DOUBTFUL,
    OUT,
    PROBABLE,
    QUESTIONABLE,
)

NBA = "nba"
SOURCE_ACTUAL = "actual"
SOURCE_REPORTED = "reported"
INFO_PREGAME = "pregame"
INFO_STANDIN = "standin"
COVERAGE_UNKNOWN = "unknown"
COVERAGE_COVERED = "covered"
STARTER_PROJECTED = "projected"
STARTER_GAME_LINEUPS = "game_lineups"

ROTATION_WINDOW = 10
ROTATION_MIN_PLAYED = 3
ROTATION_MIN_SECONDS = 15 * 60
GAME_LINEUP_FIRST_SEASON = 2025

P_OUT_BY_STATUS: dict[str, float] = {
    OUT: 1.0,
    DOUBTFUL: 0.75,
    QUESTIONABLE: 0.5,
    DAY_TO_DAY: 0.25,
    PROBABLE: 0.1,
}

# Official reports use this word. The snapshot scale does not. p_out 0 means
# the player is not absent. It is not an unknown word and it is not a guess.
AVAILABLE = "Available"
OFFICIAL_INJURY_SOURCE = "injuries_nba_official"
OFFICIAL_STALENESS = timedelta(minutes=90)
OFFICIAL_P_OUT_SCALE: dict[str, float] = {**P_OUT_BY_STATUS, AVAILABLE: 0.0}
OFFICIAL_COUNT_COLUMNS: tuple[str, ...] = (
    "rot_out_n",
    "rot_q_n",
    "unmatched_listed_n",
    "injury_report_missing",
)
TEAM_MISSING = "missing"
TEAM_NOT_SUBMITTED = "not_submitted"
TEAM_READY = "ready"

# Sum-rule markets use their stat columns. Double-double and triple-double
# have no continuous stat, so the share uses the same counting columns the
# market reads. It is not a share of double-double events.
MARKET_COMPONENTS: dict[str, tuple[str, ...]] = {
    "player_points": ("pts",),
    "player_rebounds": ("reb",),
    "player_assists": ("ast",),
    "player_threes": ("fg3m",),
    "player_steals": ("stl",),
    "player_blocks": ("blk",),
    "player_points_rebounds": ("pts", "reb"),
    "player_points_assists": ("pts", "ast"),
    "player_rebounds_assists": ("reb", "ast"),
    "player_points_rebounds_assists": ("pts", "reb", "ast"),
    "player_double_double": ("pts", "reb", "ast", "stl", "blk"),
    "player_triple_double": ("pts", "reb", "ast", "stl", "blk"),
}

SHARE_COLUMNS: tuple[str, ...] = tuple(
    f"team_missing_share_{market}" for market in CATALOG_MARKETS
)
ABSENCE_FEATURE_COLUMNS: tuple[str, ...] = (
    ("team_missing_minutes",) + SHARE_COLUMNS + ("opp_missing_minutes",)
)
CONTEXT_COLUMNS: tuple[str, ...] = ("is_starter", "player_injury_status")

COVERAGE_NOTE_UNKNOWN = (
    "source_covered is not in the schema (migration 005 is not on this branch). "
    "An empty injury list is unknown, not healthy. Pregame rows do not store "
    "zero absence features from that empty list. projected_lineup_sources is "
    "also absent, so a projected lineup is visible only when first_seen_at <= T. "
    "A backfill time after T stays invisible."
)
COVERAGE_NOTE_PRESENT = (
    "source_covered is present but this export does not read its columns, "
    "so coverage stays unknown and pregame absence features stay empty."
)
COVERAGE_NOTE_COVERED = (
    "Injury coverage was marked covered. A pregame absence feature of zero "
    "means the report listed nobody, not that the feed was missing."
)


class AbsenceError(ValueError):
    """The absence inputs cannot be read."""


@dataclass(frozen=True, slots=True)
class TeamAbsences:
    """Absence list for one team in one game.

    ``pairs`` is ``(bdl_player_id, p_out)``, sorted by player id. A player
    who is not absent is omitted. Omission is not a stored zero.
    ``unknown_status_count`` is how many rotation players had a listed row
    whose status word is blank or not on the starting scale.
    """

    pairs: tuple[tuple[int, float], ...]
    unknown_status_count: int


@dataclass(frozen=True, slots=True)
class StarterDecision:
    """Whether one player started, and which table supplied the flag.

    ``source`` is ``projected`` (known at T), ``game_lineups`` (published
    after tip, so the dataset row is a stand-in), or None when neither
    table has a usable row.
    """

    is_starter: bool | None
    source: str | None


def known_at(observed_at: datetime, as_of: datetime) -> bool:
    """Return whether a fact observed at ``observed_at`` is known at T.

    Exactly T is known. One second after T is not. ``as_of`` is the row's
    existing T. This function does not subtract hours and does not build a
    second cutoff.

    Raises:
        AbsenceError: either timestamp has no timezone.
    """
    _require_aware(observed_at, "observed_at")
    _require_aware(as_of, "as_of")
    return observed_at <= as_of


def _p_out_on_scale(status: str | None, scale: Mapping[str, float]) -> float | None:
    """Return ``scale[word]`` after trimming, or None when the word is absent."""
    if status is None:
        return None
    word = status.strip()
    if not word:
        return None
    return scale.get(word)


def p_out_for_status(status: str | None) -> float | None:
    """Map one listed status word to ``p_out``.

    Blank text and a word that is not on the starting scale return None.
    The caller counts that None and does not invent a probability. The
    comparison uses the shared injury-status constants, including
    whitespace trimmed off the stored word. Doubtful stays Doubtful.
    ``Available`` is not on this scale.
    """
    return _p_out_on_scale(status, P_OUT_BY_STATUS)


def official_p_out(status: str | None) -> float | None:
    """Map one official-report status word to ``p_out``.

    ``Available`` is 0. Out, Doubtful, Questionable, Day-To-Day, and
    Probable keep the starting weights. A blank or any other word returns
    None. The caller counts that None and does not invent a probability.
    """
    return _p_out_on_scale(status, OFFICIAL_P_OUT_SCALE)


def latest_listed_injury(
    injuries: Sequence[InjuryRecord],
    league: str,
    player_id: int,
    as_of: datetime,
) -> InjuryRecord | None:
    """Return the newest listed injury row known at T, or None.

    Rows are reduced in the same order as ``current_injuries``: the newest
    ``snapshot_at`` at or before T is chosen first, and ``listed`` is
    applied to that row only. Filtering to ``listed`` rows first would
    bring back an older Out after the player had already left the list.
    A row one second after T is ignored. A row exactly at T is eligible.

    Returns:
        The newest listed row, or None when the player has no row at T or
        the newest row is a removal.
    """
    newest: InjuryRecord | None = None
    for row in injuries:
        if row.league != league or row.bdl_player_id != player_id:
            continue
        if not known_at(row.snapshot_at, as_of):
            continue
        if newest is None or row.snapshot_at > newest.snapshot_at:
            newest = row
    if newest is None or not newest.listed:
        return None
    return newest


def own_injury_status(
    injuries: Sequence[InjuryRecord],
    league: str,
    player_id: int,
    as_of: datetime,
) -> str | None:
    """Return the player's own listed status word at T.

    An unknown word is returned trimmed, not replaced. A blank status and
    a removal return None. Stand-in dataset rows do not call this; the
    builder stores NULL there.
    """
    row = latest_listed_injury(injuries, league, player_id, as_of)
    if row is None or row.status is None:
        return None
    word = row.status.strip()
    return word or None


def team_absences(
    league: str,
    team: int,
    game: int,
    as_of: datetime,
    source: str,
    *,
    target_date: date,
    stats: Sequence[StatRecord],
    injuries: Sequence[InjuryRecord] = (),
    p_out_scale: Mapping[str, float] | None = None,
) -> TeamAbsences:
    """Return ``(bdl_player_id, p_out)`` for one team's rotation.

    Call this from the training builder with stats already in memory, and
    from the live path with :class:`app.ml.load.TeamAbsenceInputs`. The
    live bundle does not have to hold every season. A superset is safe:
    the window is still this team's last 10 games dated before
    ``target_date``.

    Args:
        league: Must be ``nba``.
        team: ``bdl_team_id`` whose rotation is being read.
        game: Target ``bdl_game_id``. Used by ``source='actual'`` to read
            that game's box score. Ignored by the rotation window.
        as_of: T for ``source='reported'``. Not recomputed.
        source: ``actual`` or ``reported``.
        target_date: ``games.date`` of the target. Games on this date are
            excluded from the rotation window.
        stats: Player-game rows. Must include the team's earlier games and,
            for ``actual``, the target game's rows for this team. Must also
            include a traded player's later game for another team, or he
            will still look like this team's rotation player.
        injuries: Snapshots for ``reported``. Rows after T may be included;
            they are ignored. Unused by ``actual``.
        p_out_scale: Status weights for ``reported``. None uses the starting
            scale. The official path passes a scale that also maps
            ``Available`` to 0. A mapped 0 is not absent, so that player is
            omitted. He is not counted as an unknown word.

    Returns:
        The absence pairs and the count of listed statuses that were not
        on the scale.

    Raises:
        AbsenceError: the league is not NBA, ``source`` is unknown,
            ``target_date`` is not a date, or a timestamp has no timezone.
    """
    if league != NBA:
        raise AbsenceError("team_absences reads NBA games only")
    if source not in (SOURCE_ACTUAL, SOURCE_REPORTED):
        raise AbsenceError("source must be actual or reported")
    if isinstance(target_date, datetime) or not isinstance(target_date, date):
        raise AbsenceError("target_date must be a date")
    _require_aware(as_of, "as_of")

    window = _window_game_ids(stats, league, team, target_date)
    window_set = set(window)
    candidates = {
        row.bdl_player_id
        for row in stats
        if row.league == league and row.bdl_team_id == team and row.bdl_game_id in window_set
    }
    target_rows = _rows_for_game(stats, league, team, game) if source == SOURCE_ACTUAL else {}
    pairs: list[tuple[int, float]] = []
    unknown = 0
    scale = P_OUT_BY_STATUS if p_out_scale is None else p_out_scale
    for player_id in sorted(candidates):
        if not _is_rotation_player(stats, league, team, target_date, player_id, window_set):
            continue
        if source == SOURCE_ACTUAL:
            target = target_rows.get(player_id)
            if target is None or target.dnp:
                pairs.append((player_id, 1.0))
            continue
        listed = latest_listed_injury(injuries, league, player_id, as_of)
        if listed is None:
            continue
        p_out = _p_out_on_scale(listed.status, scale)
        if p_out is None:
            unknown += 1
            continue
        if p_out == 0:
            continue
        pairs.append((player_id, p_out))
    return TeamAbsences(pairs=tuple(pairs), unknown_status_count=unknown)


class AbsenceIndex:
    """Indexes one league's stat rows so each team-game reads a small bundle.

    The bundle is what the live SQL returns: the team's last 10 earlier
    games, each candidate's latest earlier row, and the target game.
    """

    def __init__(self, stats: Sequence[StatRecord]) -> None:
        self._by_player: dict[tuple[str, int], list[StatRecord]] = {}
        self._team_games: dict[tuple[str, int], list[tuple[date, int]]] = {}
        self._rows_by_team_game: dict[tuple[str, int, int], list[StatRecord]] = {}
        seen_games: dict[tuple[str, int, int], date] = {}
        for row in stats:
            self._by_player.setdefault((row.league, row.bdl_player_id), []).append(row)
            game_key = (row.league, row.bdl_team_id, row.bdl_game_id)
            self._rows_by_team_game.setdefault(game_key, []).append(row)
            seen_games[game_key] = row.game_date
        for (league, team, game_id), game_date in seen_games.items():
            self._team_games.setdefault((league, team), []).append((game_date, game_id))
        for rows in self._by_player.values():
            rows.sort(key=lambda item: (item.game_date, item.bdl_game_id))
        for games in self._team_games.values():
            games.sort()

    def bundle(
        self,
        league: str,
        team: int,
        target_date: date,
        target_game_id: int,
    ) -> tuple[StatRecord, ...]:
        """Return the rows ``team_absences`` needs for one team-game."""
        games = [
            (game_date, game_id)
            for game_date, game_id in self._team_games.get((league, team), ())
            if game_date < target_date
        ]
        window = games[-ROTATION_WINDOW:]
        chosen: list[StatRecord] = []
        seen: set[tuple[int, int]] = set()
        candidates: set[int] = set()
        for _, game_id in window:
            for row in self._rows_by_team_game.get((league, team, game_id), ()):
                _add_stat(chosen, seen, row)
                candidates.add(row.bdl_player_id)
        for player_id in candidates:
            latest: StatRecord | None = None
            for row in self._by_player.get((league, player_id), ()):
                if row.game_date < target_date:
                    latest = row
                else:
                    break
            if latest is not None:
                _add_stat(chosen, seen, latest)
        for row in self._rows_by_team_game.get((league, team, target_game_id), ()):
            _add_stat(chosen, seen, row)
        return tuple(chosen)


def null_absence_features() -> dict[str, None]:
    """Absence feature columns set to NULL, including opponent minutes."""
    return {name: None for name in ABSENCE_FEATURE_COLUMNS}


def absence_features_known(*, source: str, coverage: str) -> bool:
    """Return whether absence features may be numbers rather than NULL.

    ``actual`` is a complete box score, so the numbers are real and the
    row is a stand-in. ``reported`` numbers are real only when coverage is
    ``covered``. Unknown coverage must not become a pregame zero.
    """
    if source == SOURCE_ACTUAL:
        return True
    return coverage == COVERAGE_COVERED


def absence_feature_values(
    *,
    team_result: TeamAbsences,
    opponent_result: TeamAbsences | None,
    stats: Sequence[StatRecord],
    league: str,
    team: int,
    opponent: int | None,
    target_date: date,
    player_id: int,
    known: bool,
) -> dict[str, float | None]:
    """Return the weighted minute and share features for one player-game.

    ``known`` false yields NULL for every column, including a real empty
    absence list. The player's own id is excluded from his team's totals
    and is not excluded from the opponent's minutes.

    Args:
        team_result: Absences for the player's team.
        opponent_result: Absences for the opponent, or None when the
            opponent team id is unknown.
        stats: Earlier games for both teams, plus the target game. The
            target date is excluded from the windows.
        league: League of the rows. NBA callers pass ``nba``.
        team: Player's team.
        opponent: Opponent team, or None.
        target_date: Target game date.
        player_id: The player the dataset row is about.
        known: Whether numbers are allowed. See
            :func:`absence_features_known`.

    Returns:
        ``team_missing_minutes``, one ``team_missing_share_<market>`` per
        catalog market, and ``opp_missing_minutes``.
    """
    if not known:
        return null_absence_features()
    window = set(_window_game_ids(stats, league, team, target_date))
    values: dict[str, float | None] = {
        "team_missing_minutes": _missing_minutes(
            team_result.pairs, stats, league, team, window, exclude=player_id
        ),
    }
    for market in CATALOG_MARKETS:
        values[f"team_missing_share_{market}"] = _missing_share(
            team_result.pairs,
            stats,
            league,
            team,
            window,
            MARKET_COMPONENTS[market],
            exclude=player_id,
        )
    if opponent is None or opponent_result is None:
        values["opp_missing_minutes"] = None
    else:
        opp_window = set(_window_game_ids(stats, league, opponent, target_date))
        values["opp_missing_minutes"] = _missing_minutes(
            opponent_result.pairs,
            stats,
            league,
            opponent,
            opp_window,
            exclude=None,
        )
    return values


def starter_for_player(
    *,
    league: str,
    game: int,
    team: int,
    player_id: int,
    season: int,
    as_of: datetime,
    lineups: Sequence[LineupRecord],
    projected: Sequence[ProjectedStarterRow],
) -> StarterDecision:
    """Return the starter flag known for one player.

    A projected version is usable when ``first_seen_at <= T``. Among those,
    the newest ``updated_at`` wins. BDL's projection is the five starters,
    so a player missing from that version is not a starter. That flag is
    pregame.

    ``game_lineups.starter`` is used only when no projected version is
    visible and the game's season is 2025 or later (the 2025-26 season, the
    first season that table covers). Using it makes the dataset row a
    stand-in. A player with no lineup row stays NULL. He is not guessed to
    be a bench player, because a missing row is not the five-man list.

    Non-NBA leagues return an empty decision.
    """
    if league != NBA:
        return StarterDecision(None, None)
    projected_ids = _projected_starter_ids(projected, league, game, team, as_of)
    if projected_ids is not None:
        return StarterDecision(player_id in projected_ids, STARTER_PROJECTED)
    if season < GAME_LINEUP_FIRST_SEASON:
        return StarterDecision(None, None)
    for row in lineups:
        if row.league == league and row.bdl_game_id == game and row.bdl_player_id == player_id:
            return StarterDecision(bool(row.starter), STARTER_GAME_LINEUPS)
    return StarterDecision(None, None)


def opponent_team(home_team_id: int | None, visitor_team_id: int | None, team: int) -> int | None:
    """Return the other team in the game, or None when that id was not loaded."""
    if home_team_id is not None and team == home_team_id:
        return visitor_team_id
    if visitor_team_id is not None and team == visitor_team_id:
        return home_team_id
    return None


def rows_for_final_scores(
    rows: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    """Return the rows whose scores count.

    Final evaluation uses ``info_source='pregame'`` only. A stand-in row
    used the target box score or ``game_lineups.starter``, neither of which
    is known at T.
    """
    return [row for row in rows if row.get("info_source") == INFO_PREGAME]


def coverage_note(coverage: str, relation_note: str | None = None) -> str:
    """Metadata sentence for the injury-coverage flag."""
    if coverage == COVERAGE_COVERED:
        return COVERAGE_NOTE_COVERED
    if relation_note and "present" in relation_note:
        return COVERAGE_NOTE_PRESENT
    return COVERAGE_NOTE_UNKNOWN


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise AbsenceError(f"{name} must be timezone-aware")


def _add_stat(chosen: list[StatRecord], seen: set[tuple[int, int]], row: StatRecord) -> None:
    key = (row.bdl_game_id, row.bdl_player_id)
    if key in seen:
        return
    seen.add(key)
    chosen.append(row)


def _window_game_ids(
    stats: Sequence[StatRecord],
    league: str,
    team: int,
    target_date: date,
) -> tuple[int, ...]:
    games = {
        (row.game_date, row.bdl_game_id)
        for row in stats
        if row.league == league and row.bdl_team_id == team and row.game_date < target_date
    }
    ordered = sorted(games)[-ROTATION_WINDOW:]
    return tuple(game_id for _, game_id in ordered)


def _rows_for_game(
    stats: Sequence[StatRecord],
    league: str,
    team: int,
    game: int,
) -> dict[int, StatRecord]:
    found: dict[int, StatRecord] = {}
    for row in stats:
        if row.league == league and row.bdl_team_id == team and row.bdl_game_id == game:
            found[row.bdl_player_id] = row
    return found


def _is_rotation_player(
    stats: Sequence[StatRecord],
    league: str,
    team: int,
    target_date: date,
    player_id: int,
    window: set[int],
) -> bool:
    latest_key: tuple[date, int] | None = None
    latest_team: int | None = None
    played: dict[int, int] = {}
    unknown_minutes = False
    for row in stats:
        if row.league != league or row.bdl_player_id != player_id or row.game_date >= target_date:
            continue
        key = (row.game_date, row.bdl_game_id)
        if latest_key is None or key > latest_key:
            latest_key = key
            latest_team = row.bdl_team_id
        if row.bdl_team_id != team or row.bdl_game_id not in window or row.dnp:
            continue
        if row.seconds_played is None:
            unknown_minutes = True
            continue
        played[row.bdl_game_id] = row.seconds_played
    if latest_team != team or unknown_minutes:
        return False
    if len(played) < ROTATION_MIN_PLAYED:
        return False
    return sum(played.values()) >= ROTATION_MIN_SECONDS * len(played)


def _deduped(stats: Sequence[StatRecord]) -> list[StatRecord]:
    chosen: list[StatRecord] = []
    seen: set[tuple[int, int]] = set()
    for row in stats:
        _add_stat(chosen, seen, row)
    return chosen


def _played_seconds(
    stats: Sequence[StatRecord],
    league: str,
    team: int,
    player_id: int,
    window: set[int],
) -> tuple[int, int] | None:
    played: dict[int, int] = {}
    for row in stats:
        if (
            row.league != league
            or row.bdl_player_id != player_id
            or row.bdl_team_id != team
            or row.bdl_game_id not in window
            or row.dnp
        ):
            continue
        if row.seconds_played is None:
            return None
        played[row.bdl_game_id] = row.seconds_played
    if not played:
        return None
    return sum(played.values()), len(played)


def _component_total(row: StatRecord, components: Sequence[str]) -> int | None:
    total = 0
    for name in components:
        value = getattr(row, name)
        if value is None:
            return None
        total += value
    return total


def _missing_minutes(
    pairs: Sequence[tuple[int, float]],
    stats: Sequence[StatRecord],
    league: str,
    team: int,
    window: set[int],
    *,
    exclude: int | None,
) -> float | None:
    relevant = [(player_id, p_out) for player_id, p_out in pairs if player_id != exclude]
    if not relevant:
        return 0.0
    total = 0.0
    for player_id, p_out in relevant:
        played = _played_seconds(stats, league, team, player_id, window)
        if played is None:
            return None
        seconds, count = played
        total += p_out * (seconds / count) / 60.0
    return total


def _team_component_total(
    stats: Sequence[StatRecord],
    league: str,
    team: int,
    window: set[int],
    components: Sequence[str],
) -> int | None:
    total = 0
    saw = False
    for row in _deduped(stats):
        if (
            row.league != league
            or row.bdl_team_id != team
            or row.bdl_game_id not in window
            or row.dnp
        ):
            continue
        value = _component_total(row, components)
        if value is None:
            return None
        saw = True
        total += value
    if not saw:
        return None
    return total


def _player_component_total(
    stats: Sequence[StatRecord],
    league: str,
    team: int,
    player_id: int,
    window: set[int],
    components: Sequence[str],
) -> int | None:
    total = 0
    for row in _deduped(stats):
        if (
            row.league != league
            or row.bdl_player_id != player_id
            or row.bdl_team_id != team
            or row.bdl_game_id not in window
            or row.dnp
        ):
            continue
        value = _component_total(row, components)
        if value is None:
            return None
        total += value
    return total


def _missing_share(
    pairs: Sequence[tuple[int, float]],
    stats: Sequence[StatRecord],
    league: str,
    team: int,
    window: set[int],
    components: Sequence[str],
    *,
    exclude: int | None,
) -> float | None:
    relevant = [(player_id, p_out) for player_id, p_out in pairs if player_id != exclude]
    if not relevant:
        return 0.0
    team_total = _team_component_total(stats, league, team, window, components)
    if team_total is None or team_total == 0:
        return None
    missing = 0.0
    for player_id, p_out in relevant:
        produced = _player_component_total(stats, league, team, player_id, window, components)
        if produced is None:
            return None
        missing += p_out * produced
    return missing / team_total


def _projected_starter_ids(
    projected: Sequence[ProjectedStarterRow],
    league: str,
    game: int,
    team: int,
    as_of: datetime,
) -> frozenset[int] | None:
    versions: dict[datetime, set[int]] = {}
    for row in projected:
        if row.league != league or row.bdl_game_id != game or row.bdl_team_id != team:
            continue
        if not known_at(row.first_seen_at, as_of):
            continue
        versions.setdefault(row.updated_at, set()).add(row.bdl_player_id)
    if not versions:
        return None
    newest = max(versions)
    return frozenset(versions[newest])


@dataclass(frozen=True, slots=True)
class OfficialTeamRead:
    """One team's slice of the official report known at T.

    ``kind`` is ``missing`` when no report is usable, ``not_submitted`` when
    that team is NOT YET SUBMITTED, or ``ready`` when the report covers the
    team. A team that the report simply does not mention is ``ready`` with
    an empty absence list, which becomes 0 minutes. ``statuses`` is
    ``(bdl_player_id, status word)`` for rotation players named on the
    report. ``unmatched_listed_n`` is None unless the team is ready.
    """

    kind: str
    result: TeamAbsences | None
    statuses: tuple[tuple[int, str], ...]
    unmatched_listed_n: int | None


def blank_official_counts() -> dict[str, None]:
    """The four official count columns, all NULL.

    Used when this row is not on the official reported path, including a
    box-score stand-in. A stand-in must not store a count in these columns.
    """
    return {name: None for name in OFFICIAL_COUNT_COLUMNS}


def features_when_official_report_missing() -> dict[str, object]:
    """Absence columns when no official report can be used at T.

    Every minute, share, count, and status is NULL. ``injury_report_missing``
    is 1. Minutes are not filled with 0: a missing report is not a healthy
    team.
    """
    columns: dict[str, object] = dict(null_absence_features())
    columns.update(blank_official_counts())
    columns["injury_report_missing"] = 1
    columns["player_injury_status"] = None
    return columns


def select_official_report(
    rows: Sequence[OfficialReportRow],
    league: str,
    game_id: int,
    as_of: datetime,
) -> tuple[OfficialReportRow, ...] | None:
    """Return every line of the latest official report for one game at T.

    ``as_of`` is the row's existing T. This function does not subtract
    hours. A line counts when ``report_at <= as_of``. Exactly T counts.
    One second after T does not. Lines for another ``bdl_game_id`` are
    ignored, even when they name the same player at the same timestamp.

    Returns:
        The lines of that one report, or None when this game has no report
        at or before T.

    Raises:
        AbsenceError: a timestamp has no timezone.
    """
    _require_aware(as_of, "as_of")
    chosen: datetime | None = None
    for row in rows:
        if row.league != league or row.bdl_game_id != game_id:
            continue
        _require_aware(row.report_at, "report_at")
        if not known_at(row.report_at, as_of):
            continue
        if chosen is None or row.report_at > chosen:
            chosen = row.report_at
    if chosen is None:
        return None
    return tuple(
        row
        for row in rows
        if row.league == league and row.bdl_game_id == game_id and row.report_at == chosen
    )


def official_source_covered(
    refreshes: Sequence[OfficialRefresh],
    league: str,
    as_of: datetime,
    *,
    staleness: timedelta = OFFICIAL_STALENESS,
) -> bool:
    """Return whether ``injuries_nba_official`` was covered at T.

    Same rule as ``source_covered``: the newest complete refresh at or
    before T must be no older than ``staleness`` (default 90 minutes). An
    incomplete refresh does not count. A refresh after T does not count.
    False means the features stay NULL. It does not mean the team is healthy.

    Raises:
        AbsenceError: a timestamp has no timezone, or ``staleness`` is negative.
    """
    _require_aware(as_of, "as_of")
    if staleness < timedelta(0):
        raise AbsenceError("staleness must be >= 0")
    latest: datetime | None = None
    for row in refreshes:
        if row.league != league or not row.complete:
            continue
        _require_aware(row.refreshed_at, "refreshed_at")
        if not known_at(row.refreshed_at, as_of):
            continue
        if latest is None or row.refreshed_at > latest:
            latest = row.refreshed_at
    if latest is None:
        return False
    return latest >= as_of - staleness


def official_player_status(
    rows: Sequence[OfficialReportRow],
    league: str,
    game_id: int,
    team: int,
    player_id: int,
    as_of: datetime,
) -> str | None:
    """Return the player's own status word on the report known at T.

    A player who is not on that report returns None. The word is trimmed
    and otherwise unchanged, including ``Available``.
    """
    report = select_official_report(rows, league, game_id, as_of)
    if report is None:
        return None
    return _status_word(tuple(row for row in report if row.bdl_team_id == team), player_id)


def read_official_team(
    rows: Sequence[OfficialReportRow],
    refreshes: Sequence[OfficialRefresh],
    *,
    league: str,
    team: int,
    game: int,
    as_of: datetime,
    target_date: date,
    stats: Sequence[StatRecord],
) -> OfficialTeamRead:
    """Read one team's official absences at T through ``team_absences``.

    No usable report returns ``missing`` and does not call ``team_absences``.
    NOT YET SUBMITTED returns ``not_submitted`` and does not call it either.
    Any other team, including one the report does not mention, calls
    ``team_absences`` with the official scale. An empty list is a real zero,
    not a missing feed.

    Raises:
        AbsenceError: ``team_absences`` rejects the inputs.
    """
    report = select_official_report(rows, league, game, as_of)
    covered = official_source_covered(refreshes, league, as_of)
    if report is None or not covered:
        return OfficialTeamRead(TEAM_MISSING, None, (), None)
    team_rows = tuple(row for row in report if row.bdl_team_id == team)
    if any(row.not_yet_submitted for row in team_rows):
        return OfficialTeamRead(TEAM_NOT_SUBMITTED, None, (), None)
    result = team_absences(
        league,
        team,
        game,
        as_of,
        SOURCE_REPORTED,
        target_date=target_date,
        stats=stats,
        injuries=_injuries_from_official(team_rows),
        p_out_scale=OFFICIAL_P_OUT_SCALE,
    )
    return OfficialTeamRead(
        TEAM_READY,
        result,
        _rotation_statuses(stats, league, team, target_date, team_rows),
        _unmatched_listed(team_rows),
    )


def official_columns_for_player(
    team_read: OfficialTeamRead,
    opponent_read: OfficialTeamRead | None,
    *,
    stats: Sequence[StatRecord],
    league: str,
    team: int,
    opponent: int | None,
    target_date: date,
    player_id: int,
    own_status: str | None,
) -> dict[str, object]:
    """Minute, share, and count columns for one player on the official path.

    A missing report uses :func:`features_when_official_report_missing`.
    A NOT YET SUBMITTED team leaves that team's columns NULL and still
    fills the opponent when the opponent's read is ready. The player's own
    id is left out of his team's minutes and out of ``rot_out_n`` and
    ``rot_q_n``. He is not left out of the opponent's minutes.

    ``stats`` must hold earlier games for both teams. The target date is
    excluded by the same window ``absence_feature_values`` already uses.
    """
    if team_read.kind == TEAM_MISSING:
        return features_when_official_report_missing()
    columns: dict[str, object] = dict(null_absence_features())
    columns.update(blank_official_counts())
    columns["injury_report_missing"] = 0
    columns["player_injury_status"] = own_status if team_read.kind == TEAM_READY else None
    opp_ready = (
        opponent_read is not None
        and opponent_read.kind == TEAM_READY
        and opponent_read.result is not None
        and opponent is not None
    )
    opp_result = opponent_read.result if opp_ready and opponent_read is not None else None
    if team_read.kind == TEAM_READY and team_read.result is not None:
        values = absence_feature_values(
            team_result=team_read.result,
            opponent_result=opp_result,
            stats=stats,
            league=league,
            team=team,
            opponent=opponent if opp_result is not None else None,
            target_date=target_date,
            player_id=player_id,
            known=True,
        )
        columns.update(values)
        out_n, q_n = _rot_counts(team_read.statuses, player_id)
        columns["rot_out_n"] = out_n
        columns["rot_q_n"] = q_n
        columns["unmatched_listed_n"] = team_read.unmatched_listed_n
        return columns
    if opp_result is not None and opponent is not None:
        opp_values = absence_feature_values(
            team_result=opp_result,
            opponent_result=None,
            stats=stats,
            league=league,
            team=opponent,
            opponent=None,
            target_date=target_date,
            player_id=-1,
            known=True,
        )
        columns["opp_missing_minutes"] = opp_values["team_missing_minutes"]
    return columns


def _injuries_from_official(rows: Sequence[OfficialReportRow]) -> tuple[InjuryRecord, ...]:
    """Matched player lines as snapshot rows so ``team_absences`` can read them.

    Unmatched names and team markers are omitted. They are counted elsewhere.
    ``snapshot_at`` is the report time. ``listed`` stays true: an official
    line is a listing, not a removal.
    """
    found: list[InjuryRecord] = []
    for row in rows:
        if row.bdl_player_id is None or row.status is None:
            continue
        if row.not_yet_submitted or row.all_players_available:
            continue
        found.append(
            InjuryRecord(
                league=row.league,
                snapshot_at=row.report_at,
                bdl_player_id=row.bdl_player_id,
                listed=True,
                status=row.status,
            )
        )
    return tuple(found)


def _status_word(rows: Sequence[OfficialReportRow], player_id: int) -> str | None:
    for row in rows:
        if row.bdl_player_id != player_id or row.status is None:
            continue
        word = row.status.strip()
        if word:
            return word
    return None


def _rotation_statuses(
    stats: Sequence[StatRecord],
    league: str,
    team: int,
    target_date: date,
    team_rows: Sequence[OfficialReportRow],
) -> tuple[tuple[int, str], ...]:
    """Rotation players on this team and the status word the report gave them.

    The rotation test is :func:`_is_rotation_player`. A rotation player the
    report does not name is omitted. Omission is not a status.
    """
    window = set(_window_game_ids(stats, league, team, target_date))
    candidates = {
        row.bdl_player_id
        for row in stats
        if row.league == league and row.bdl_team_id == team and row.bdl_game_id in window
    }
    found: list[tuple[int, str]] = []
    for player_id in sorted(candidates):
        if not _is_rotation_player(stats, league, team, target_date, player_id, window):
            continue
        word = _status_word(team_rows, player_id)
        if word is None:
            continue
        found.append((player_id, word))
    return tuple(found)


def _rot_counts(statuses: Sequence[tuple[int, str]], player_id: int) -> tuple[int, int]:
    """Return ``(rot_out_n, rot_q_n)``, leaving out the row's own player.

    Out and Doubtful count as out. Questionable is the other count.
    Probable, Available, and any other word count as neither.
    """
    out_n = 0
    q_n = 0
    for pid, word in statuses:
        if pid == player_id:
            continue
        if word in (OUT, DOUBTFUL):
            out_n += 1
        elif word == QUESTIONABLE:
            q_n += 1
    return out_n, q_n


def _is_g_league(row: OfficialReportRow) -> bool:
    text = " ".join(part for part in (row.category, row.reason) if part).casefold()
    return "g league" in text or "g-league" in text


def _unmatched_listed(rows: Sequence[OfficialReportRow]) -> int:
    """Non-G-League player lines on this team that have no ``bdl_player_id``.

    A G League line with no id is ignored. A matched id is not unmatched.
    Team markers are not player lines.
    """
    count = 0
    for row in rows:
        if row.not_yet_submitted or row.all_players_available:
            continue
        if row.player_raw.strip() == "" or row.bdl_player_id is not None:
            continue
        if _is_g_league(row):
            continue
        count += 1
    return count
