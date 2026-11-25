"""The one p_out table for official injury statuses, and the fitter for it.

Feature code reads :data:`P_OUT_BY_OFFICIAL_STATUS`. The five numbers live
here only. ``WEIGHT_TABLE_SOURCE`` is ``prior`` until a real 2024-25 fit
is written into that dict. The prior numbers are the old fixed scale.
They are not a measured did-not-play rate.

One fit row is one player in one game:

- ``season`` — the training season. 2024 means the 2024-25 season.
- ``bdl_game_id``
- ``bdl_player_id``
- ``status`` — the official word on the latest report with ``report_at <= T``
- ``report_at`` — that report's time
- ``as_of`` — T, from :func:`app.ml.asof.prediction_instant` (tip minus 3 hours)
- ``did_not_play`` — true when that game's box-score row has ``dnp``

A weight is one number per status: ``did_not_play_count / row_count``,
with both counts. A player with no box-score row has no label and is left
out. A report at T counts. A report one second later does not. A game whose
``season`` is not 2024 is not a fit row.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.ml.asof import DEFAULT_HOURS_BEFORE_TIP, prediction_instant
from app.ml.load import GameRecord, OfficialReportRow, StatRecord
from app.services.injury_status import DAY_TO_DAY, DOUBTFUL, OUT, PROBABLE, QUESTIONABLE

# 2024 is the start year of the 2024-25 season, matching ``games.season``.
TRAINING_SEASON = 2024
AVAILABLE = "Available"
OFFICIAL_STATUSES: tuple[str, ...] = (OUT, DOUBTFUL, QUESTIONABLE, PROBABLE, AVAILABLE)
_OFFICIAL = frozenset(OFFICIAL_STATUSES)

# "prior" means the old fixed scale. A measured 2024-25 fit would set this
# to "fit_2024_25" in the same change that replaces the numbers below.
WEIGHT_TABLE_SOURCE = "prior"
P_OUT_BY_OFFICIAL_STATUS: dict[str, float] = {
    OUT: 1.0,
    DOUBTFUL: 0.75,
    QUESTIONABLE: 0.5,
    PROBABLE: 0.1,
    AVAILABLE: 0.0,
}

# Day-To-Day is a snapshot word. Official reports do not use it, so it is
# not in the table above and it is not fit from those reports.
DAY_TO_DAY_P_OUT = 0.25


class WeightFitError(ValueError):
    """The fit rows cannot be turned into a weight."""


@dataclass(frozen=True, slots=True)
class FitObservation:
    """One player in one game, with the status known at T and the box label.

    ``did_not_play`` comes from that game's box score. It is not an injury
    status from a later report.
    """

    season: int
    bdl_game_id: int
    bdl_player_id: int
    status: str
    report_at: datetime
    as_of: datetime
    did_not_play: bool


@dataclass(frozen=True, slots=True)
class StatusWeight:
    """How often one official status sat out.

    ``p_out`` is ``did_not_play_count / row_count``. It is None when
    ``row_count`` is 0, so an empty status is not stored as 0.
    """

    status: str
    row_count: int
    did_not_play_count: int

    @property
    def p_out(self) -> float | None:
        if self.row_count == 0:
            return None
        return self.did_not_play_count / self.row_count


@dataclass(frozen=True, slots=True)
class WeightFit:
    """One weight for every official status, in :data:`OFFICIAL_STATUSES` order.

    ``season`` is the only season whose games were allowed into the counts.
    """

    season: int
    weights: tuple[StatusWeight, ...]

    def weight_for(self, status: str) -> StatusWeight:
        for row in self.weights:
            if row.status == status:
                return row
        raise KeyError(status)


def snapshot_scale() -> dict[str, float]:
    """Weights for ``injury_snapshots``.

    Out, Doubtful, Questionable, and Probable are copied from the official
    table at call time. Day-To-Day keeps :data:`DAY_TO_DAY_P_OUT`. Available
    is not on this scale.
    """
    table = _official_numbers()
    return {
        OUT: table[OUT],
        DOUBTFUL: table[DOUBTFUL],
        QUESTIONABLE: table[QUESTIONABLE],
        DAY_TO_DAY: DAY_TO_DAY_P_OUT,
        PROBABLE: table[PROBABLE],
    }


def official_scale() -> dict[str, float]:
    """Weights for an official report line.

    The five official words come from :data:`P_OUT_BY_OFFICIAL_STATUS`.
    Day-To-Day is added so a snapshot word on this path still maps. Adding
    it does not copy a second set of the five numbers.
    """
    scale = _official_numbers()
    scale[DAY_TO_DAY] = DAY_TO_DAY_P_OUT
    return scale


def _official_numbers() -> dict[str, float]:
    missing = [word for word in OFFICIAL_STATUSES if word not in P_OUT_BY_OFFICIAL_STATUS]
    if missing:
        raise KeyError("official weight table is missing " + ", ".join(missing))
    return {word: P_OUT_BY_OFFICIAL_STATUS[word] for word in OFFICIAL_STATUSES}


def collect_fit_observations(
    games: Sequence[GameRecord],
    rows: Sequence[OfficialReportRow],
    stats: Sequence[StatRecord],
    *,
    season: int = TRAINING_SEASON,
    hours_before_tip: float = DEFAULT_HOURS_BEFORE_TIP,
    league: str = "nba",
) -> tuple[FitObservation, ...]:
    """Build fit rows from games, official lines, and box scores.

    ``season`` must be :data:`TRAINING_SEASON`. Games from any other season
    are ignored. For each kept game, T is :func:`prediction_instant` and the
    status is the latest report :func:`app.ml.absence.select_official_report`
    returns. A line with no ``bdl_player_id``, a blank status, or a word
    outside the five official statuses is not a fit row. Two different
    statuses for one player on that report drop the player. A player with
    no box-score row in that game is not labeled.

    Raises:
        WeightFitError: ``season`` is not the training season, or a selected
            report is after T.
        ValueError: a tip time has no timezone, or ``hours_before_tip`` is negative.
    """
    if season != TRAINING_SEASON:
        raise WeightFitError("weights are fit on the 2024-25 season only")
    from app.ml.absence import select_official_report

    box = _box_dnp(stats, league)
    found: list[FitObservation] = []
    for game in games:
        if game.league != league or game.season != season:
            continue
        instant = prediction_instant(game.game_date, game.datetime_utc, hours_before_tip)
        report = select_official_report(rows, league, game.bdl_game_id, instant.as_of)
        if report is None:
            continue
        for line in report:
            if line.report_at > instant.as_of:
                raise WeightFitError("selected report is after T")
        for player_id, (status, report_at) in _statuses(report).items():
            label = box.get((game.bdl_game_id, player_id))
            if label is None:
                continue
            if report_at > instant.as_of:
                raise WeightFitError("selected report is after T")
            found.append(
                FitObservation(
                    season=game.season,
                    bdl_game_id=game.bdl_game_id,
                    bdl_player_id=player_id,
                    status=status,
                    report_at=report_at,
                    as_of=instant.as_of,
                    did_not_play=label,
                )
            )
    found.sort(key=lambda item: (item.bdl_game_id, item.bdl_player_id))
    return tuple(found)


def rates_from_observations(
    observations: Sequence[FitObservation],
    *,
    season: int = TRAINING_SEASON,
) -> WeightFit:
    """Count did-not-play rates. Every official status is returned.

    A row from another season, a row whose report is after T, or a status
    outside the five official words is refused. Refusal is the leak check:
    those rows are not added to a count.

    Raises:
        WeightFitError: a row is outside the training season, after T, or
            not an official status. ``season`` must be 2024.
    """
    if season != TRAINING_SEASON:
        raise WeightFitError("weights are fit on the 2024-25 season only")
    for row in observations:
        if row.season != season:
            raise WeightFitError("fit row is outside the 2024-25 season")
        if row.report_at > row.as_of:
            raise WeightFitError("fit row uses a report after T")
        if row.status not in _OFFICIAL:
            raise WeightFitError("fit row status is not an official status")
    counts = {status: [0, 0] for status in OFFICIAL_STATUSES}
    for row in observations:
        counts[row.status][0] += 1
        counts[row.status][1] += int(row.did_not_play)
    weights = tuple(
        StatusWeight(status=status, row_count=counts[status][0], did_not_play_count=counts[status][1])
        for status in OFFICIAL_STATUSES
    )
    return WeightFit(season=season, weights=weights)


def fit_official_status_weights(
    games: Sequence[GameRecord],
    rows: Sequence[OfficialReportRow],
    stats: Sequence[StatRecord],
    *,
    season: int = TRAINING_SEASON,
    hours_before_tip: float = DEFAULT_HOURS_BEFORE_TIP,
    league: str = "nba",
) -> WeightFit:
    """Fit p_out for each official status from T-time reports and box scores.

    This does not write :data:`P_OUT_BY_OFFICIAL_STATUS`. The caller records
    a measured table only after checking the season, the counts, and the
    T rule. A fixture fit must not be stored as the 2024-25 rate.
    """
    observations = collect_fit_observations(
        games,
        rows,
        stats,
        season=season,
        hours_before_tip=hours_before_tip,
        league=league,
    )
    return rates_from_observations(observations, season=season)


def _box_dnp(stats: Sequence[StatRecord], league: str) -> dict[tuple[int, int], bool]:
    """Map ``(game, player)`` to the box-score ``dnp`` flag.

    Two rows that disagree are dropped. A missing key means there is no label.
    """
    seen: dict[tuple[int, int], bool] = {}
    conflict: set[tuple[int, int]] = set()
    for row in stats:
        if row.league != league:
            continue
        key = (row.bdl_game_id, row.bdl_player_id)
        if key in conflict:
            continue
        previous = seen.get(key)
        if previous is not None and previous != row.dnp:
            conflict.add(key)
            del seen[key]
            continue
        seen[key] = row.dnp
    return seen


def _statuses(report: Sequence[OfficialReportRow]) -> dict[int, tuple[str, datetime]]:
    """One official status per matched player on the already chosen report.

    A player with two different status words is omitted. Unmatched lines
    and team markers are omitted.
    """
    words: dict[int, set[str]] = {}
    reported_at: dict[int, datetime] = {}
    for line in report:
        if line.bdl_player_id is None or line.status is None:
            continue
        if line.not_yet_submitted or line.all_players_available:
            continue
        word = line.status.strip()
        if not word:
            continue
        words.setdefault(line.bdl_player_id, set()).add(word)
        reported_at[line.bdl_player_id] = line.report_at
    chosen: dict[int, tuple[str, datetime]] = {}
    for player_id, found in words.items():
        if len(found) != 1:
            continue
        word = next(iter(found))
        if word not in _OFFICIAL:
            continue
        chosen[player_id] = (word, reported_at[player_id])
    return chosen
