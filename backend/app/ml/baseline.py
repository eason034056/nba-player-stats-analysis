"""Pregame baseline: one player-game row, features known at T, lines for grading.

The dataset export (``python -m app.ml.build_dataset``) already builds the
row. This module does not build a second one. A training row is one
player-game. Features are columns on that export that are knowable at the
row's ``as_of`` (T). Labels are ``y_<market>``. Prop lines are not features.
A line is eligible only when ``snapshot_at`` is present and
``snapshot_at <= T``.

Headline rows are ``info_source = pregame`` and ``season_type =
regular_season``. Training uses season 2024 (2024-25). Validation uses
season 2025 (2025-26) for reporting. Season 2026 (2026-27) is not used to
fit or to choose the model. Official injury columns are not features.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.ml.absence import ABSENCE_FEATURE_COLUMNS, CONTEXT_COLUMNS
from app.ml.asof import T_RULE
from app.ml.features import COUNT_COLUMNS, form_column_names
from app.ml.game_odds import ODDS_COLUMNS, median_value
from app.ml.labels import CATALOG_MARKETS, label_column_names

TRAIN_SEASON = 2024
VALIDATE_SEASON = 2025
EXCLUDED_SEASON = 2026
HEADLINE_INFO_SOURCE = "pregame"
HEADLINE_SEASON_TYPE = "regular_season"
SEED = 158

SPLIT_VALIDATION = "season_2025_regular_season_pregame"
SPLIT_SIDE = "season_2025_non_regular_pregame"

SUM_MARKETS: tuple[str, ...] = CATALOG_MARKETS[:10]
BINARY_MARKETS: tuple[str, ...] = CATALOG_MARKETS[10:]

# Last-10 played mean, or last-5 when last-10 is missing. Combo markets add
# the component means. The same parts the stat uses, not a prop line.
NAIVE_COMPONENTS: dict[str, tuple[str, ...]] = {
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
}

# Named so a headline list that grows into these columns fails closed.
OFFICIAL_INJURY_COLUMNS: tuple[str, ...] = (
    "nba_injury_report_rows",
    "injuries_nba_official",
    "current_injuries",
    "source_covered",
)
POST_TIP_COLUMNS: tuple[str, ...] = (
    "home_score",
    "visitor_score",
    "pts",
    "reb",
    "ast",
    "fg3m",
    "stl",
    "blk",
    "seconds_played",
    "dnp",
)
LINE_COLUMNS: tuple[str, ...] = (
    "player_prop_snapshots",
    "line",
    "over_odds",
    "under_odds",
    "milestone_odds",
)
IDENTITY_COLUMNS: tuple[str, ...] = (
    "league",
    "season",
    "date",
    "bdl_game_id",
    "bdl_player_id",
    "bdl_team_id",
    "season_type",
    "info_source",
    "as_of",
    "tip_fallback",
)

KIND_RANK = {"opening": 0, "live": 1, "closing": 2}
UTC = timezone.utc


class BaselineError(ValueError):
    """The baseline inputs break a point-in-time or split rule."""


def headline_feature_names() -> tuple[str, ...]:
    """Return the locked pregame feature list, in matrix order.

    Schedule counts, home flag, played-game means, and opening game-odds
    columns. ``season_type`` is a filter (regular season), not a column of
    the matrix. Absence, starter, injury words, labels, and prop lines are
    not in this list.
    """
    return ("is_home",) + COUNT_COLUMNS + form_column_names() + ODDS_COLUMNS


def excluded_feature_names() -> tuple[str, ...]:
    """Return columns the headline matrix must not contain."""
    return (
        OFFICIAL_INJURY_COLUMNS
        + POST_TIP_COLUMNS
        + LINE_COLUMNS
        + ABSENCE_FEATURE_COLUMNS
        + CONTEXT_COLUMNS
        + IDENTITY_COLUMNS
        + label_column_names()
    )


def forbidden_names_in(names: Sequence[str]) -> tuple[str, ...]:
    """Return names from ``names`` that the headline matrix must reject."""
    blocked = set(excluded_feature_names())
    found: list[str] = []
    for name in names:
        if name in blocked or name.startswith("y_"):
            found.append(name)
    return tuple(found)


def assert_headline_feature_list(names: Sequence[str]) -> None:
    """Raise when ``names`` is not the locked pregame list.

    A forbidden column fails first, so an official-injury name or a prop
    line is named in the error. Any other addition fails the lock.

    Raises:
        BaselineError: the list contains a forbidden column, or it is not
            exactly :func:`headline_feature_names`.
    """
    leaked = forbidden_names_in(names)
    if leaked:
        raise BaselineError(
            "headline features include forbidden columns: " + ", ".join(leaked)
        )
    locked = headline_feature_names()
    if tuple(names) != locked:
        raise BaselineError("headline feature list does not match the locked pregame set")


def assert_seasons_for_fit(seasons: Sequence[int], *, role: str) -> None:
    """Raise when a fit or a selection set includes 2026-27 or later.

    Args:
        seasons: Season integers on the rows about to be fit or used to
            choose a model.
        role: Short name of that set, included in the error.

    Raises:
        BaselineError: any season is greater than or equal to 2026.
    """
    bad = sorted({int(season) for season in seasons if int(season) >= EXCLUDED_SEASON})
    if bad:
        raise BaselineError(
            f"{role} includes season {bad[0]} (2026-27 or later). "
            "That season is not used for training or selection."
        )


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise BaselineError(f"{name} must be timezone-aware")


def line_visible_at_t(snapshot_at: datetime | None, as_of: datetime) -> bool:
    """Return whether one prop snapshot may grade a row at T.

    A missing timestamp is not visible and is not filled in. Exactly T is
    visible. One second after T is not. ``as_of`` is the row's existing T.
    This function does not subtract hours and does not build a second cutoff.

    Raises:
        BaselineError: a present timestamp has no timezone.
    """
    if snapshot_at is None:
        return False
    _require_aware(snapshot_at, "snapshot_at")
    _require_aware(as_of, "as_of")
    return snapshot_at <= as_of


@dataclass(frozen=True, slots=True)
class PropLine:
    """One book line for one player, game, and market.

    ``snapshot_at`` may be missing. A missing timestamp is not used.
    ``line`` is the posted number, not a feature of the model.
    """

    league: str
    bdl_game_id: int
    bdl_player_id: int
    book_key: str
    market: str
    snapshot_kind: str
    snapshot_at: datetime | None
    line: float


def _line_rank(row: PropLine) -> tuple[datetime, int, float]:
    if row.snapshot_at is None:
        raise BaselineError("a visible line has no timestamp")
    return (row.snapshot_at, KIND_RANK[row.snapshot_kind], row.line)


def median_line_at_t(lines: Sequence[PropLine], *, as_of: datetime) -> float | None:
    """Return the median of the latest pre-T line per book.

    Rows with a null timestamp, an unknown kind, or ``snapshot_at`` after
    ``as_of`` are left out. Each remaining book keeps one row: the greatest
    timestamp, then closing over live over opening when the timestamp ties.
    The median of those book lines is the grade line. No eligible book
    returns None, which is a missing line, not a zero.

    Args:
        lines: Snapshots for one player, game, and market. Other markets
            must already have been filtered by the caller.
        as_of: T for the player-game.

    Returns:
        The median line, or None when no book is eligible.

    Raises:
        BaselineError: a timestamp has no timezone, or a kind is not
            opening, live, or closing.
    """
    best: dict[str, PropLine] = {}
    for row in lines:
        if row.snapshot_kind not in KIND_RANK:
            raise BaselineError(f"unknown snapshot_kind {row.snapshot_kind!r}")
        if not line_visible_at_t(row.snapshot_at, as_of):
            continue
        current = best.get(row.book_key)
        if current is None or _line_rank(row) > _line_rank(current):
            best[row.book_key] = row
    return median_value([row.line for row in best.values()])


def _cell_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value)


def naive_projection(row: Mapping[str, object], market: str) -> float | None:
    """Return the last-10 mean for ``market``, or last-5 when last-10 is null.

    Each component uses its own window. A component with both windows null
    makes the whole projection null. The null is counted; it is not filled
    with zero. Combo markets sum the component projections.

    Args:
        row: One player-game, with the export's ``<stat>_last_10`` columns.
        market: A sum-rule catalog market.

    Returns:
        The naive stat, or None when a component has no window.
    """
    total = 0.0
    for stat in NAIVE_COMPONENTS[market]:
        last_10 = _cell_float(row.get(f"{stat}_last_10"))
        if last_10 is not None:
            total += last_10
            continue
        last_5 = _cell_float(row.get(f"{stat}_last_5"))
        if last_5 is None:
            return None
        total += last_5
    return total


def _numeric_array(series: pd.Series) -> np.ndarray:
    values = [_cell_float(value) for value in series.tolist()]
    return np.array([np.nan if value is None else value for value in values], dtype=np.float64)


def feature_matrix(
    frame: pd.DataFrame,
    names: Sequence[str] | None = None,
) -> tuple[np.ndarray, tuple[str, ...]]:
    """Return the headline numeric matrix for ``frame``.

    Missing values stay NaN. Booleans become 0 or 1. The column order is
    :func:`headline_feature_names`. Extra columns on ``frame``, including
    injury fields and prop lines, are not copied in.

    Args:
        frame: Player-game rows from the dataset export.
        names: Feature list to lock. The default is the headline list.
            Tests pass a bad list to show the guard.

    Returns:
        The array shaped ``(rows, features)`` and the names in that order.

    Raises:
        BaselineError: the list is not the locked pregame set, or a locked
            column is missing from ``frame``.
    """
    chosen = tuple(names) if names is not None else headline_feature_names()
    assert_headline_feature_list(chosen)
    missing = [name for name in chosen if name not in frame.columns]
    if missing:
        raise BaselineError("dataset is missing headline columns: " + ", ".join(missing))
    columns = [_numeric_array(frame[name]) for name in chosen]
    if not columns:
        return np.zeros((len(frame), 0), dtype=np.float64), chosen
    return np.column_stack(columns), chosen


@dataclass(frozen=True, slots=True)
class DatasetSplit:
    """Rows after the season, source, and season-type filters.

    ``validation`` still includes a row whose labels are all null. The
    scorer counts that row as void and does not grade it. ``side`` is
    2025-26 pregame rows that are not regular season. It is scored after
    the fit and is not used to choose the model.
    """

    train: pd.DataFrame
    validation: pd.DataFrame
    side: pd.DataFrame
    excluded_season_2026: pd.DataFrame
    excluded_not_pregame: pd.DataFrame
    ignored_other: pd.DataFrame


def _season_numbers(frame: pd.DataFrame) -> pd.Series:
    seasons = pd.to_numeric(frame["season"], errors="coerce")
    if seasons.isna().any():
        raise BaselineError("every row needs a season")
    return seasons.astype(int)


def split_dataset(frame: pd.DataFrame) -> DatasetSplit:
    """Split one export into train, validation, and the rows that stay out.

    Train is season 2024, regular season, ``pregame``. Validation is season
    2025, regular season, ``pregame``. Season 2026 and later is excluded
    before those masks, so it cannot land in train or validation. A non
    pregame row is excluded. A 2025 pregame row that is not regular season
    goes to the side table.

    Args:
        frame: Rows with the dataset export columns.

    Returns:
        The six groups. Indexes are reset so a later array lines up.

    Raises:
        BaselineError: a required column is missing, a season is missing,
            or the train or validation seasons include 2026-27.
    """
    required = (
        "league",
        "season",
        "bdl_game_id",
        "bdl_player_id",
        "info_source",
        "season_type",
        "as_of",
        *headline_feature_names(),
        *label_column_names(),
    )
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise BaselineError("dataset is missing columns: " + ", ".join(missing))
    seasons = _season_numbers(frame)
    future = seasons >= EXCLUDED_SEASON
    pregame = frame["info_source"].astype(str) == HEADLINE_INFO_SOURCE
    regular = frame["season_type"].astype(str) == HEADLINE_SEASON_TYPE
    rest = ~future
    not_pregame = rest & ~pregame
    side = rest & pregame & ~regular & (seasons == VALIDATE_SEASON)
    train_mask = rest & pregame & regular & (seasons == TRAIN_SEASON)
    valid_mask = rest & pregame & regular & (seasons == VALIDATE_SEASON)
    used = future | not_pregame | side | train_mask | valid_mask

    def _take(mask: pd.Series) -> pd.DataFrame:
        return frame.loc[mask].reset_index(drop=True)

    split = DatasetSplit(
        train=_take(train_mask),
        validation=_take(valid_mask),
        side=_take(side),
        excluded_season_2026=_take(future),
        excluded_not_pregame=_take(not_pregame),
        ignored_other=_take(~used),
    )
    assert_seasons_for_fit(_season_numbers(split.train).tolist(), role="training")
    assert_seasons_for_fit(_season_numbers(split.validation).tolist(), role="validation")
    assert_seasons_for_fit(_season_numbers(split.side).tolist(), role="side_table")
    return split


def _aware_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        return None
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        _require_aware(value, "as_of")
        return value.astimezone(UTC)
    text = str(value).strip()
    if not text or text.lower() in {"nat", "none", "null"}:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    _require_aware(parsed, "as_of")
    return parsed.astimezone(UTC)


def line_values_for_frame(
    frame: pd.DataFrame,
    grouped: Mapping[tuple[str, int, int, str], Sequence[PropLine]],
    market: str,
) -> np.ndarray:
    """Return one grade line per row, or NaN when the row has none.

    The lookup key is league, game, player, and market. A row with no T
    gets NaN, because a line cannot be shown to be at or before T.
    """
    out = np.full(len(frame), np.nan, dtype=np.float64)
    leagues = frame["league"].tolist()
    games = frame["bdl_game_id"].tolist()
    players = frame["bdl_player_id"].tolist()
    stamps = frame["as_of"].tolist()
    for index, (league, game, player, stamp) in enumerate(zip(leagues, games, players, stamps)):
        as_of = _aware_datetime(stamp)
        if as_of is None:
            continue
        key = (str(league), int(game), int(player), market)
        value = median_line_at_t(grouped.get(key, ()), as_of=as_of)
        if value is not None:
            out[index] = value
    return out


def index_prop_lines(
    lines: Sequence[PropLine],
) -> dict[tuple[str, int, int, str], list[PropLine]]:
    """Group prop lines by league, game, player, and market."""
    grouped: dict[tuple[str, int, int, str], list[PropLine]] = {}
    for row in lines:
        key = (row.league, row.bdl_game_id, row.bdl_player_id, row.market)
        grouped.setdefault(key, []).append(row)
    return grouped


def naive_column(frame: pd.DataFrame, market: str) -> np.ndarray:
    """Return :func:`naive_projection` for every row of ``frame``."""
    records = frame.to_dict(orient="records")
    values = [naive_projection(record, market) for record in records]
    return np.array([np.nan if value is None else value for value in values], dtype=np.float64)


def label_column(frame: pd.DataFrame, market: str) -> np.ndarray:
    """Return ``y_<market>`` as floats. Null labels are NaN."""
    return _numeric_array(frame[f"y_{market}"])


def _finite_mean(values: np.ndarray) -> float | None:
    if values.size == 0:
        return None
    return float(np.mean(values))


def residual_bins(actual: np.ndarray, predicted: np.ndarray) -> list[dict[str, object]]:
    """Bin ``actual - predicted`` into below -5, within 5, and above 5.

    Each bin carries its row count and its mean residual. An empty bin has
    a null mean. The bins cover every finite residual once.
    """
    residual = actual - predicted
    groups = (
        ("below_-5", residual < -5),
        ("within_5", (residual >= -5) & (residual <= 5)),
        ("above_5", residual > 5),
    )
    bins: list[dict[str, object]] = []
    for name, mask in groups:
        chosen = residual[mask]
        bins.append(
            {
                "bin": name,
                "row_count": int(chosen.size),
                "mean_residual": _finite_mean(chosen),
            }
        )
    return bins


def reliability_table(actual: np.ndarray, probability: np.ndarray) -> list[dict[str, object]]:
    """Bin predicted probabilities and report the observed rate in each bin.

    Bins are ``[0, 0.2)``, ``[0.2, 0.4)``, ``[0.4, 0.6)``, ``[0.6, 0.8)``,
    and ``[0.8, 1]``. The last bin includes 1. Each bin carries its row
    count, the mean predicted probability, and the mean outcome.
    """
    edges = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    rows: list[dict[str, object]] = []
    for start, stop in zip(edges, edges[1:]):
        if stop == 1.0:
            mask = (probability >= start) & (probability <= stop)
        else:
            mask = (probability >= start) & (probability < stop)
        chosen_y = actual[mask]
        chosen_p = probability[mask]
        rows.append(
            {
                "bin_low": start,
                "bin_high": stop,
                "row_count": int(chosen_y.size),
                "mean_predicted": _finite_mean(chosen_p),
                "mean_outcome": _finite_mean(chosen_y),
            }
        )
    return rows


def score_regression(
    *,
    split: str,
    y: np.ndarray,
    predicted: np.ndarray,
    naive: np.ndarray,
    lines: np.ndarray,
) -> dict[str, object]:
    """Score one sum-rule market and keep the coverage counts on every number.

    ``rows_scored`` is the labeled rows. ``rows_with_usable_line`` plus
    ``rows_without_line`` equals ``rows_scored``. A missing line stays in
    ``rows_scored`` and in the MAE. It is not dropped before the rate is
    computed. A push (actual equals the line) stays in
    ``rows_with_usable_line`` and leaves the hit-rate denominator, the same
    idea as ``player_hit_rate``. A prediction that lands on the line is not
    given a side; it is counted and left out of the hit-rate denominator.

    MAE is the mean absolute error on ``rows_scored``. The naive MAE uses
    the labeled rows whose last-10 (or last-5) projection exists.
    ``mae_on_naive_rows`` is the model MAE on that same subset.

    Args:
        split: Name of the row set, stored on the result.
        y: Labels. NaN is a null label.
        predicted: Model predictions, aligned with ``y``.
        naive: Last-10 / last-5 projections, aligned with ``y``.
        lines: Grade lines. NaN means no usable pre-T line.

    Returns:
        The metric dict. Rates are null when their denominator is 0.
    """
    labeled = ~np.isnan(y)
    has_line = labeled & ~np.isnan(lines)
    actual_push = has_line & (y == lines)
    prediction_on_line = has_line & ~actual_push & (predicted == lines)
    over_hit = has_line & (y > lines) & (predicted > lines)
    under_hit = has_line & (y < lines) & (predicted < lines)
    hits = over_hit | under_hit
    misses = has_line & ~actual_push & ~prediction_on_line & ~hits
    naive_ok = labeled & ~np.isnan(naive)
    rows_scored = int(labeled.sum())
    hit_rows = int(hits.sum() + misses.sum())
    error = np.abs(y[labeled] - predicted[labeled])
    naive_error = np.abs(y[naive_ok] - naive[naive_ok])
    model_on_naive = np.abs(y[naive_ok] - predicted[naive_ok])
    return {
        "task": "regression",
        "split": split,
        "rows_in_split": int(y.size),
        "rows_scored": rows_scored,
        "rows_label_null": int((~labeled).sum()),
        "rows_with_usable_line": int(has_line.sum()),
        "rows_without_line": int((labeled & ~has_line).sum()),
        "mae": _finite_mean(error),
        "mae_row_count": rows_scored,
        "naive_last10_mae": _finite_mean(naive_error),
        "naive_row_count": int(naive_ok.sum()),
        "naive_missing_count": int((labeled & np.isnan(naive)).sum()),
        "mae_on_naive_rows": _finite_mean(model_on_naive),
        "mae_on_naive_row_count": int(naive_ok.sum()),
        "hits": int(hits.sum()),
        "misses": int(misses.sum()),
        "pushes": int(actual_push.sum()),
        "prediction_on_line": int(prediction_on_line.sum()),
        "hit_rate": (None if hit_rows == 0 else float(hits.sum()) / hit_rows),
        "hit_rate_row_count": hit_rows,
        "calibration": {
            "kind": "binned_residual",
            "residual": "actual_minus_predicted",
            "row_count": rows_scored,
            "bins": residual_bins(y[labeled], predicted[labeled]),
        },
    }


def _log_loss(actual: np.ndarray, probability: np.ndarray) -> float | None:
    if actual.size == 0:
        return None
    clipped = np.clip(probability, 1e-15, 1 - 1e-15)
    loss = actual * np.log(clipped) + (1.0 - actual) * np.log(1.0 - clipped)
    return float(-np.mean(loss))


def score_probability(
    *,
    split: str,
    y: np.ndarray,
    probability: np.ndarray,
    train_rate: float | None,
    lines: np.ndarray,
) -> dict[str, object]:
    """Score one yes/no market. Brier and log loss use every labeled row.

    The naive comparison is the training positive rate, a constant
    probability on the same labeled rows. Hit rate uses a pre-T line when
    one exists: the actual and the predicted probability are each compared
    with that line. Pushes leave the hit-rate denominator. Rows with no
    line stay in the Brier count and in ``rows_without_line``.

    Args:
        split: Name of the row set.
        y: 0/1 labels. NaN is a null label.
        probability: Predicted probability of the 1 class.
        train_rate: Share of training labels that are 1. None when the
            training market had no labeled rows.
        lines: Grade lines. NaN means no usable pre-T line.

    Returns:
        The metric dict, including a reliability table.
    """
    labeled = ~np.isnan(y)
    has_line = labeled & ~np.isnan(lines)
    actual_push = has_line & (y == lines)
    prediction_on_line = has_line & ~actual_push & (probability == lines)
    over_hit = has_line & (y > lines) & (probability > lines)
    under_hit = has_line & (y < lines) & (probability < lines)
    hits = over_hit | under_hit
    misses = has_line & ~actual_push & ~prediction_on_line & ~hits
    rows_scored = int(labeled.sum())
    hit_rows = int(hits.sum() + misses.sum())
    y_ok = y[labeled]
    p_ok = probability[labeled]
    brier = None if rows_scored == 0 else float(np.mean((p_ok - y_ok) ** 2))
    naive_brier = None
    if rows_scored and train_rate is not None:
        naive_brier = float(np.mean((train_rate - y_ok) ** 2))
    return {
        "task": "probability",
        "split": split,
        "rows_in_split": int(y.size),
        "rows_scored": rows_scored,
        "rows_label_null": int((~labeled).sum()),
        "rows_with_usable_line": int(has_line.sum()),
        "rows_without_line": int((labeled & ~has_line).sum()),
        "brier": brier,
        "brier_row_count": rows_scored,
        "log_loss": _log_loss(y_ok, p_ok),
        "log_loss_row_count": rows_scored,
        "naive_train_rate": train_rate,
        "naive_brier": naive_brier,
        "naive_brier_row_count": rows_scored if train_rate is not None else 0,
        "hits": int(hits.sum()),
        "misses": int(misses.sum()),
        "pushes": int(actual_push.sum()),
        "prediction_on_line": int(prediction_on_line.sum()),
        "hit_rate": (None if hit_rows == 0 else float(hits.sum()) / hit_rows),
        "hit_rate_row_count": hit_rows,
        "calibration": {
            "kind": "reliability",
            "row_count": rows_scored,
            "bins": reliability_table(y_ok, p_ok),
        },
    }


def parse_prop_line(row: Mapping[str, object]) -> PropLine:
    """Build one :class:`PropLine` from a JSON object.

    Raises:
        BaselineError: a required field is missing, the kind is unknown,
            the line is not a finite number, or a timestamp has no timezone.
    """
    required = (
        "league",
        "bdl_game_id",
        "bdl_player_id",
        "book_key",
        "market",
        "snapshot_kind",
        "line",
    )
    missing = [name for name in required if name not in row]
    if missing:
        raise BaselineError("prop line is missing fields: " + ", ".join(missing))
    kind = str(row["snapshot_kind"])
    if kind not in KIND_RANK:
        raise BaselineError(f"unknown snapshot_kind {kind!r}")
    line = _cell_float(row["line"])
    if line is None or not math.isfinite(line):
        raise BaselineError("prop line must be a finite number")
    return PropLine(
        league=str(row["league"]),
        bdl_game_id=int(row["bdl_game_id"]),
        bdl_player_id=int(row["bdl_player_id"]),
        book_key=str(row["book_key"]),
        market=str(row["market"]),
        snapshot_kind=kind,
        snapshot_at=_aware_datetime(row.get("snapshot_at")),
        line=line,
    )


def positive_rate(y: np.ndarray) -> float | None:
    """Return the share of non-null labels equal to 1, or None if none exist."""
    labeled = y[~np.isnan(y)]
    if labeled.size == 0:
        return None
    return float(np.mean(labeled == 1))


# Re-exported so the metrics file can quote the same sentence as the export.
T_RULE_TEXT = T_RULE
