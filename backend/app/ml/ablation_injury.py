"""Ablation: do official T-time injury features help the pregame baseline?

One arm is a name, a feature-column list, and a source rule. Every measured
arm is scored on one shared row set: the 2025-26 regular-season pregame rows
the last-10 naive can score. The fit still uses the trainer.

Run from ``backend/``::

    DATABASE_URL="" python -m app.ml.ablation_injury \\
        --dataset <pregame.parquet> \\
        --standin-dataset <standin.parquet> \\
        --out <ablation.json> \\
        --report <ablation.md>

``--dataset`` is the default ``build_dataset`` export (``--absence-source
reported``). ``--standin-dataset`` is a second export with
``--absence-source actual``. The official arm never reads that second file.
The stand-in arm never writes into the official count columns.

This command does not open a database, does not write ``predictions``, and
does not turn official features on in the production trainer.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

from app.ml.absence import (
    ABSENCE_FEATURE_COLUMNS,
    INFO_STANDIN,
    OFFICIAL_COUNT_COLUMNS,
    official_p_out,
)
from app.ml.baseline import (
    EXCLUDED_SEASON,
    OFFICIAL_INJURY_COLUMNS,
    SEED,
    BaselineError,
    DatasetSplit,
    PropLine,
    _numeric_array,
    assert_seasons_for_fit,
    headline_feature_names,
    index_prop_lines,
    label_column,
    line_values_for_frame,
    naive_column,
    positive_rate,
    score_probability,
    score_regression,
    split_dataset,
)
from app.ml.labels import CATALOG_MARKETS
from app.ml.train_baseline import (
    BINARY_MARKETS,
    CLASSIFIER_PARAMS,
    REGRESSOR_PARAMS,
    SUM_MARKETS,
    FittedBaseline,
    _missing_columns,
    _params,
    _predict_probability,
    _predict_regression,
    _row_counts,
    _take_columns,
    fit_baseline,
    load_dataset,
    load_prop_lines,
    write_metrics,
)

logger = logging.getLogger(__name__)

PLAYER_P_OUT = "player_injury_p_out"
GATED_TEXT = (
    "not measurable: official coverage 0 rows. "
    "With 0 coverage, keep the official path gated/dark; "
    "re-run after the 2024-25 official reports are backfilled."
)
DROPPED_TEXT = (
    "not measurable: every official column was missing on every training row "
    "and was dropped, so the fit is the no-official baseline. "
    "Keep the official path gated. Re-run when training rows have official values."
)
PINBALL_NOTE = (
    "The point model gives q=0.5 only. The trainer has no quantile model, "
    "so pinball at 0.25 and 0.75 is not scored."
)
SCORED_ROW_RULE = (
    "Season 2025 regular-season pregame rows where every catalog label is "
    "present and the last-10/last-5 naive exists for every sum market. "
    "Every measured arm is scored on this same set. Season 2026-27 is not in it."
)
TRAIN_RULE = (
    "Season 2024 regular-season pregame. The full training split is fit. "
    "The comparison, not the fit, is limited to the shared naive rows."
)

OFFICIAL_SOURCE_RULE = (
    "Pregame rows only. Baseline columns, plus the minute and share columns "
    "and the four official counts that the official path writes, plus "
    "player_injury_p_out mapped from player_injury_status by official_p_out "
    "(the SPO-154 table, not a refit). "
    "baseline.OFFICIAL_INJURY_COLUMNS are source-table locks, not export columns. "
    "Stand-in rows are not read."
)
NO_OFFICIAL_SOURCE_RULE = (
    "Pregame rows only. The locked SPO-158 headline list and nothing else."
)
STANDIN_SOURCE_RULE = (
    "Same pregame row keys. Baseline columns come from the pregame export. "
    "Minute, share, and is_starter come from the source=actual export "
    "(box score) or a game_lineups.starter row. Those rows are info_source "
    "standin. Official count columns are not features and must stay empty there."
)
NAIVE_SOURCE_RULE = (
    "No fit. Last-10 played mean, with last-5 when last-10 is missing. "
    "Same naive_projection as the SPO-158 trainer. "
    "Double-double and triple-double use the training positive rate."
)

DOCUMENTED_PREGAME_EXPORT = (
    "python -m app.ml.build_dataset --dsn-env ML_DATABASE_URL "
    "--seasons 2023:2025 --hours-before-tip 3 --out <pregame.parquet>"
)
DOCUMENTED_STANDIN_EXPORT = (
    "python -m app.ml.build_dataset --dsn-env ML_DATABASE_URL "
    "--seasons 2023:2025 --hours-before-tip 3 --absence-source actual "
    "--out <standin.parquet>"
)
DOCUMENTED_COMMAND = (
    'DATABASE_URL="" python -m app.ml.ablation_injury '
    "--dataset <pregame.parquet> --standin-dataset <standin.parquet> "
    "--out <ablation.json> --report <ablation.md>"
)


class AblationError(ValueError):
    """The ablation inputs break a split, a source rule, or the row set."""


@dataclass(frozen=True, slots=True)
class Arm:
    """One ablation arm.

    ``feature_columns`` is the matrix order. ``source_rule`` says which
    file those columns are read from. The naive arm has no feature columns
    because it does not fit.
    """

    name: str
    feature_columns: tuple[str, ...]
    source_rule: str


def official_value_columns() -> tuple[str, ...]:
    """Columns that count as an official injury value on an export row.

    These are the fields the official path writes: minutes, shares, the
    four counts, and the player's own status word. A null is missing. A
    zero is a real value. ``baseline.OFFICIAL_INJURY_COLUMNS`` are not in
    this list; they are source names, not export columns.
    """
    return ABSENCE_FEATURE_COLUMNS + OFFICIAL_COUNT_COLUMNS + ("player_injury_status",)


def official_feature_columns() -> tuple[str, ...]:
    """Matrix columns for the official arm, baseline first."""
    return headline_feature_names() + ABSENCE_FEATURE_COLUMNS + OFFICIAL_COUNT_COLUMNS + (PLAYER_P_OUT,)


def standin_feature_columns() -> tuple[str, ...]:
    """Matrix columns for the box-score stand-in arm.

    Official count columns are absent on purpose.
    """
    blocked = set(OFFICIAL_COUNT_COLUMNS)
    names = headline_feature_names() + ABSENCE_FEATURE_COLUMNS + ("is_starter",)
    leaked = [name for name in names if name in blocked]
    if leaked:
        raise AblationError("stand-in arm includes official count columns: " + ", ".join(leaked))
    return names


def no_official_feature_columns() -> tuple[str, ...]:
    """The locked SPO-158 list."""
    return headline_feature_names()


def assert_frame_allowed(frame: pd.DataFrame, *, role: str) -> None:
    """Raise when ``frame`` includes a 2026-27 row.

    ``role`` is ``training`` or ``selection``. The fit frame and the frame
    whose metrics pick the recommendation both pass through here. Season
    2026 is not used for either.

    Raises:
        AblationError: any season is 2026 or later, or the season column
            is missing.
    """
    if frame.empty:
        return
    if "season" not in frame.columns:
        raise AblationError(f"{role} frame has no season column")
    try:
        assert_seasons_for_fit([int(value) for value in frame["season"].tolist()], role=role)
    except BaselineError as exc:
        raise AblationError(str(exc)) from exc


def assert_standin_rows_leave_official_counts_empty(
    frame: pd.DataFrame,
    *,
    require_standin: bool,
) -> None:
    """Raise when a stand-in row has a value in an official count column.

    The box-score path leaves ``rot_out_n``, ``rot_q_n``,
    ``unmatched_listed_n``, and ``injury_report_missing`` null. A number
    in one of those columns on a stand-in row was copied in.

    Args:
        frame: The stand-in export, or the pregame file (which may contain
            a few stand-in rows).
        require_standin: When true, every row must be ``info_source=standin``.
            That is the stand-in export. The pregame file uses false.

    Raises:
        AblationError: a stand-in row has a non-null official count, or the
            stand-in export is not entirely stand-in.
    """
    if frame.empty or "info_source" not in frame.columns:
        if require_standin and not frame.empty:
            raise AblationError("stand-in export has a row whose info_source is not standin")
        return
    standin = frame["info_source"].astype(str) == INFO_STANDIN
    if require_standin and not bool(standin.all()):
        raise AblationError("stand-in export has a row whose info_source is not standin")
    if not bool(standin.any()):
        return
    rows = frame.loc[standin]
    for name in OFFICIAL_COUNT_COLUMNS:
        if name not in rows.columns:
            continue
        if bool(rows[name].notna().any()):
            raise AblationError(f"stand-in values appear in official column {name}")


def assert_same_scored_rows(key_lists: Mapping[str, Sequence[tuple[object, ...]]]) -> None:
    """Raise when two measured arms were scored on different player-games.

    Args:
        key_lists: Arm name to the scored keys, in row order.

    Raises:
        AblationError: the key tuples differ.
    """
    names = list(key_lists)
    if len(names) < 2:
        return
    first_name = names[0]
    first = tuple(key_lists[first_name])
    for name in names[1:]:
        other = tuple(key_lists[name])
        if other != first:
            raise AblationError(
                "arms are scored on different row sets: "
                f"{first_name} has {len(first)} rows and {name} has {len(other)} rows"
            )


def _status_to_p_out(value: object) -> float | None:
    """Map one status cell through :func:`official_p_out`. Null stays null."""
    if value is None or isinstance(value, bool):
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        return None
    if not isinstance(value, str):
        return None
    return official_p_out(value)


def _p_out_column(frame: pd.DataFrame) -> np.ndarray:
    if "player_injury_status" not in frame.columns:
        return np.full(len(frame), np.nan, dtype=np.float64)
    values = [_status_to_p_out(value) for value in frame["player_injury_status"].tolist()]
    return np.array([np.nan if value is None else value for value in values], dtype=np.float64)


def numeric_matrix(frame: pd.DataFrame, names: Sequence[str]) -> np.ndarray:
    """Return a float matrix for ``names``.

    A missing headline column is an error. A missing extra column is an
    all-null column, which the training drop list can remove. Nulls stay
    null. This does not call :func:`feature_matrix`, so the production lock
    on the 28 headline names stays in place.

    Raises:
        AblationError: a locked headline column is missing.
    """
    locked = set(headline_feature_names())
    columns: list[np.ndarray] = []
    for name in names:
        if name == PLAYER_P_OUT:
            columns.append(_p_out_column(frame))
            continue
        if name not in frame.columns:
            if name in locked:
                raise AblationError("dataset is missing headline columns: " + name)
            columns.append(np.full(len(frame), np.nan, dtype=np.float64))
            continue
        columns.append(_numeric_array(frame[name]))
    if not columns:
        return np.zeros((len(frame), 0), dtype=np.float64)
    return np.column_stack(columns)


def official_coverage_count(frame: pd.DataFrame) -> int:
    """Return how many rows have any non-missing official injury value."""
    if frame.empty:
        return 0
    mask = np.zeros(len(frame), dtype=bool)
    for name in official_value_columns():
        if name not in frame.columns:
            continue
        if name == "player_injury_status":
            flags = [_status_text(value) for value in frame[name].tolist()]
            mask |= np.array(flags, dtype=bool)
            continue
        mask |= ~np.isnan(_numeric_array(frame[name]))
    return int(mask.sum())


def _status_text(value: object) -> bool:
    """True when the cell is a non-empty status word, including an unknown word.

    Unknown words are still official values. They do not become a p_out.
    """
    if value is None or isinstance(value, bool):
        return False
    try:
        if pd.isna(value):
            return False
    except TypeError:
        return False
    if not isinstance(value, str):
        return False
    text = value.strip()
    return text != "" and text.lower() not in {"none", "nan", "<na>"}


def row_keys(frame: pd.DataFrame) -> tuple[tuple[object, ...], ...]:
    """Return ``(league, season, game, player)`` for each row, in order."""
    keys: list[tuple[object, ...]] = []
    for league, season, game, player in zip(
        frame["league"].tolist(),
        frame["season"].tolist(),
        frame["bdl_game_id"].tolist(),
        frame["bdl_player_id"].tolist(),
    ):
        keys.append((str(league), int(season), int(game), int(player)))
    return tuple(keys)


def _require_unique(frame: pd.DataFrame, role: str) -> None:
    keys = row_keys(frame)
    if len(keys) != len(set(keys)):
        raise AblationError(f"{role} has a duplicate player-game")


def _naive_ready(frame: pd.DataFrame) -> np.ndarray:
    """True on rows the naive can score and every catalog label is present."""
    ready = np.ones(len(frame), dtype=bool)
    for market in SUM_MARKETS:
        ready &= ~np.isnan(naive_column(frame, market))
    for market in CATALOG_MARKETS:
        ready &= ~np.isnan(label_column(frame, market))
    return ready


def fit_arm(train: pd.DataFrame, names: Sequence[str], seed: int) -> FittedBaseline:
    """Fit one arm on ``train``.

    The locked headline list is delegated to :func:`fit_baseline`. A wider
    list uses that function's drop rule, hyperparameters, and model classes.
    ``feature_matrix`` is not called with the wider list: that function
    rejects anything except the production 28 names, and the production
    trainer must keep rejecting them.

    Raises:
        AblationError: the season, the source, or the labels are not a
            legal training set, or every column is missing.
    """
    assert_frame_allowed(train, role="training")
    if train.empty:
        raise AblationError("the training split has no rows")
    if not (train["info_source"].astype(str) == "pregame").all():
        raise AblationError("training rows must be info_source pregame")
    if not (train["season_type"].astype(str) == "regular_season").all():
        raise AblationError("training rows must be regular_season")
    chosen = tuple(names)
    if chosen == tuple(headline_feature_names()):
        return fit_baseline(train, seed)
    full = numeric_matrix(train, chosen)
    kept, dropped = _missing_columns(full, chosen)
    if not kept:
        raise AblationError("every feature is missing on every training row")
    matrix = _take_columns(full, chosen, kept)
    fitted: dict[str, object] = {}
    for market in SUM_MARKETS:
        y = label_column(train, market)
        mask = ~np.isnan(y)
        if int(mask.sum()) == 0:
            raise AblationError(f"{market} has no training labels")
        model = HistGradientBoostingRegressor(**_params(REGRESSOR_PARAMS, seed))
        model.fit(matrix[mask], y[mask])
        fitted[market] = model
    for market in BINARY_MARKETS:
        y = label_column(train, market)
        mask = ~np.isnan(y)
        classes = {int(value) for value in y[mask].tolist()}
        if classes != {0, 1}:
            raise AblationError(f"{market} training labels must include both 0 and 1")
        model = HistGradientBoostingClassifier(**_params(CLASSIFIER_PARAMS, seed))
        model.fit(matrix[mask], y[mask].astype(int))
        fitted[market] = model
    return FittedBaseline(
        models=fitted,
        features_actually_fit=kept,
        features_dropped_all_missing_in_train=dropped,
    )


def _pinball_half(y: np.ndarray, predicted: np.ndarray) -> float | None:
    """Pinball loss at q=0.5 on the labeled rows. This is half of MAE."""
    labeled = ~np.isnan(y)
    if not bool(labeled.any()):
        return None
    residual = y[labeled] - predicted[labeled]
    loss = np.where(residual >= 0.0, 0.5 * residual, -0.5 * residual)
    return float(np.mean(loss))


def _stamp_regression(block: dict[str, object], arm_name: str, y: np.ndarray, predicted: np.ndarray) -> dict[str, object]:
    stamped = dict(block)
    stamped["arm"] = arm_name
    stamped["pinball_q"] = 0.5
    stamped["pinball"] = _pinball_half(y, predicted)
    stamped["pinball_row_count"] = stamped["rows_scored"]
    stamped["pinball_q25"] = None
    stamped["pinball_q75"] = None
    stamped["quantile_models"] = False
    return stamped


def _stamp_probability(block: dict[str, object], arm_name: str) -> dict[str, object]:
    stamped = dict(block)
    stamped["arm"] = arm_name
    stamped["pinball_q25"] = None
    stamped["pinball_q75"] = None
    stamped["quantile_models"] = False
    return stamped


def score_fitted_arm(
    frame: pd.DataFrame,
    fitted: FittedBaseline,
    names: Sequence[str],
    train: pd.DataFrame,
    grouped_lines: Mapping[tuple[str, int, int, str], Sequence[PropLine]],
    arm_name: str,
) -> dict[str, dict[str, object]]:
    """Score ``fitted`` on ``frame`` with the trainer's metric functions.

    Raises:
        AblationError: ``frame`` contains a 2026-27 row, or a market's
            scored-row count is not the length of ``frame``.
    """
    assert_frame_allowed(frame, role="selection")
    chosen = tuple(names)
    full = numeric_matrix(frame, chosen)
    matrix = _take_columns(full, chosen, fitted.features_actually_fit)
    markets: dict[str, dict[str, object]] = {}
    for market in SUM_MARKETS:
        y = label_column(frame, market)
        predicted = _predict_regression(fitted.models[market], matrix)
        block = _stamp_regression(
            score_regression(
                split="season_2025_regular_season_pregame_naive_rows",
                y=y,
                predicted=predicted,
                naive=naive_column(frame, market),
                lines=line_values_for_frame(frame, grouped_lines, market),
            ),
            arm_name,
            y,
            predicted,
        )
        if int(block["rows_scored"]) != len(frame):
            raise AblationError("arms are scored on different row sets")
        markets[market] = block
    for market in BINARY_MARKETS:
        block = _stamp_probability(
            score_probability(
                split="season_2025_regular_season_pregame_naive_rows",
                y=label_column(frame, market),
                probability=_predict_probability(fitted.models[market], matrix),
                train_rate=positive_rate(label_column(train, market)),
                lines=line_values_for_frame(frame, grouped_lines, market),
            ),
            arm_name,
        )
        if int(block["rows_scored"]) != len(frame):
            raise AblationError("arms are scored on different row sets")
        markets[market] = block
    return markets


def score_naive_arm(
    frame: pd.DataFrame,
    train: pd.DataFrame,
    grouped_lines: Mapping[tuple[str, int, int, str], Sequence[PropLine]],
) -> dict[str, dict[str, object]]:
    """Score the last-10 naive on ``frame``. Binary markets use the train rate."""
    assert_frame_allowed(frame, role="selection")
    markets: dict[str, dict[str, object]] = {}
    for market in SUM_MARKETS:
        naive = naive_column(frame, market)
        y = label_column(frame, market)
        block = _stamp_regression(
            score_regression(
                split="season_2025_regular_season_pregame_naive_rows",
                y=y,
                predicted=naive,
                naive=naive,
                lines=line_values_for_frame(frame, grouped_lines, market),
            ),
            "naive_last10",
            y,
            naive,
        )
        if int(block["rows_scored"]) != len(frame):
            raise AblationError("arms are scored on different row sets")
        markets[market] = block
    for market in BINARY_MARKETS:
        y = label_column(frame, market)
        rate = positive_rate(label_column(train, market))
        probability = np.full(len(frame), np.nan if rate is None else rate, dtype=np.float64)
        block = _stamp_probability(
            score_probability(
                split="season_2025_regular_season_pregame_naive_rows",
                y=y,
                probability=probability,
                train_rate=rate,
                lines=line_values_for_frame(frame, grouped_lines, market),
            ),
            "naive_last10",
        )
        if int(block["rows_scored"]) != len(frame):
            raise AblationError("arms are scored on different row sets")
        markets[market] = block
    return markets


def _index_standin(frame: pd.DataFrame) -> dict[tuple[object, ...], dict[str, object]]:
    _require_unique(frame, "stand-in export")
    index: dict[tuple[object, ...], dict[str, object]] = {}
    records = frame.to_dict(orient="records")
    for key, record in zip(row_keys(frame), records):
        index[key] = record
    return index


def attach_standin_features(
    pregame: pd.DataFrame,
    standin_index: Mapping[tuple[object, ...], Mapping[str, object]],
) -> pd.DataFrame:
    """Copy stand-in minute, share, and starter columns onto pregame keys.

    Baseline columns stay on the pregame row. Official count columns are
    not written. A missing key becomes null for the stand-in columns.

    Raises:
        AblationError: this copy changes an official count column.
    """
    extra = [name for name in standin_feature_columns() if name not in set(headline_feature_names())]
    out = pregame.copy()
    keys = row_keys(pregame)
    for name in extra:
        values: list[object] = []
        for key in keys:
            source = standin_index.get(key)
            values.append(None if source is None else source.get(name))
        out[name] = values
    for name in OFFICIAL_COUNT_COLUMNS:
        if name not in pregame.columns or name not in out.columns:
            continue
        if not _same_values(pregame[name], out[name]):
            raise AblationError(f"stand-in values appear in official column {name}")
    return out


def _same_values(before: pd.Series, after: pd.Series) -> bool:
    """True when two columns match, treating null as equal to null."""
    before_missing = before.isna().to_numpy()
    after_missing = after.isna().to_numpy()
    if not np.array_equal(before_missing, after_missing):
        return False
    kept = ~before_missing
    return before.to_numpy()[kept].tolist() == after.to_numpy()[kept].tolist()


def _standin_covers(
    standin_index: Mapping[tuple[object, ...], Mapping[str, object]],
    frames: Sequence[pd.DataFrame],
) -> bool:
    for frame in frames:
        for key in row_keys(frame):
            if key not in standin_index:
                return False
    return True


def _metric_row_count(block: Mapping[str, object]) -> int:
    if block.get("task") == "regression":
        return int(block["mae_row_count"])
    return int(block["brier_row_count"])


def _outcome(left: object, right: object) -> str:
    if left is None or right is None:
        return "skip"
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return "skip"
    if float(left) < float(right) - 1e-12:
        return "win"
    if float(left) > float(right) + 1e-12:
        return "loss"
    return "tie"


def decide(
    coverage_rows: int,
    official_markets: Mapping[str, Mapping[str, object]] | None,
    baseline_markets: Mapping[str, Mapping[str, object]] | None,
    scored_rows: int,
) -> tuple[str, str]:
    """Choose ship, don't-ship, ship-some, or not measurable.

    Lower MAE wins a sum market. Lower Brier wins a yes/no market. A tie
    is not a win. The production model is not changed by any of these
    sentences. Coverage 0 never reads the errors.

    Raises:
        AblationError: a compared market was scored on different row counts.
    """
    if coverage_rows == 0:
        return "not_measurable", GATED_TEXT
    if official_markets is None or baseline_markets is None:
        return "not_measurable", DROPPED_TEXT
    wins: list[str] = []
    rest: list[str] = []
    for market in SUM_MARKETS:
        official = official_markets[market]
        baseline = baseline_markets[market]
        if _metric_row_count(official) != _metric_row_count(baseline):
            raise AblationError("arms are scored on different row sets")
        outcome = _outcome(official.get("mae"), baseline.get("mae"))
        if outcome == "win":
            wins.append(market)
        elif outcome != "skip":
            rest.append(market)
    for market in BINARY_MARKETS:
        official = official_markets[market]
        baseline = baseline_markets[market]
        if _metric_row_count(official) != _metric_row_count(baseline):
            raise AblationError("arms are scored on different row sets")
        outcome = _outcome(official.get("brier"), baseline.get("brier"))
        if outcome == "win":
            wins.append(market)
        elif outcome != "skip":
            rest.append(market)
    if wins and not rest:
        text = (
            f"ship: official injury features have lower error than the no-official "
            f"baseline on all {len(wins)} markets, on {scored_rows} shared validation rows. "
            "Production still leaves those features off."
        )
        return "ship", text
    if wins and rest:
        text = (
            "ship-some: official injury features have lower error on "
            f"{', '.join(wins)} and not on {', '.join(rest)}, "
            f"on {scored_rows} shared validation rows. "
            "Production still leaves those features off."
        )
        return "ship_some", text
    text = (
        "don't-ship: official injury features do not have lower error than the "
        f"no-official baseline on the {scored_rows} shared validation rows. "
        "Production still leaves those features off."
    )
    return "dont_ship", text


def _arm_payload(
    arm: Arm,
    *,
    status: str,
    reason: str | None,
    fitted: FittedBaseline | None,
    markets: dict[str, dict[str, object]] | None,
    coverage_rows: int,
    validation_rows: int,
    scored_rows: int | None,
) -> dict[str, object]:
    dropped: list[str] = []
    kept: list[str] = []
    if fitted is not None:
        dropped = list(fitted.features_dropped_all_missing_in_train)
        kept = list(fitted.features_actually_fit)
    return {
        "name": arm.name,
        "status": status,
        "reason": reason,
        "source_rule": arm.source_rule,
        "feature_columns": list(arm.feature_columns),
        "features_dropped_all_missing_in_train": dropped,
        "features_actually_fit": kept,
        "official_coverage_rows": coverage_rows,
        "validation_rows": validation_rows,
        "scored_row_count": scored_rows,
        "markets": markets,
    }


def _official_columns_used(fitted: FittedBaseline) -> list[str]:
    extra = set(official_feature_columns()) - set(headline_feature_names())
    return [name for name in fitted.features_actually_fit if name in extra]


def _season_list(frame: pd.DataFrame) -> list[int]:
    if frame.empty:
        return []
    return sorted({int(value) for value in frame["season"].tolist()})


def load_embedded_standin(path: Path) -> pd.DataFrame | None:
    """Return ``standin_rows`` from a JSON object, or None when absent.

    A list file and a Parquet file have no embedded stand-in table.
    ``--standin-dataset`` overrides this.
    """
    if path.suffix != ".json":
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "standin_rows" not in payload:
        return None
    rows = payload["standin_rows"]
    if not isinstance(rows, list):
        raise AblationError("standin_rows must be a list")
    return pd.DataFrame(rows)


def run_ablation(
    dataset: pd.DataFrame,
    standin: pd.DataFrame | None,
    lines: Sequence[PropLine],
    seed: int = SEED,
) -> dict[str, object]:
    """Fit the four arms and write the comparison dict.

    The official arm is not given market scores when official coverage on
    the validation split is 0, or when every official column was dropped
    in training. Those cases are not a comparison.

    Raises:
        AblationError: a 2026-27 row is in the fit or the selection set,
            stand-in values sit in official count columns, measured arms
            do not share a row set, or the validation split has no row
            the naive can score.
    """
    import sklearn

    assert_standin_rows_leave_official_counts_empty(dataset, require_standin=False)
    if standin is not None:
        assert_standin_rows_leave_official_counts_empty(standin, require_standin=True)
    split: DatasetSplit = split_dataset(dataset)
    assert_frame_allowed(split.train, role="training")
    assert_frame_allowed(split.validation, role="selection")
    _require_unique(split.train, "training")
    _require_unique(split.validation, "validation")
    ready = _naive_ready(split.validation)
    scored = split.validation.loc[ready].reset_index(drop=True)
    if scored.empty:
        raise AblationError("no validation row has a naive projection and labels")
    assert_frame_allowed(scored, role="selection")
    scored_keys = row_keys(scored)
    coverage_rows = official_coverage_count(split.validation)
    train_coverage = official_coverage_count(split.train)
    grouped = index_prop_lines(lines)

    no_official_arm = Arm("no_official", no_official_feature_columns(), NO_OFFICIAL_SOURCE_RULE)
    no_official_fit = fit_arm(split.train, no_official_arm.feature_columns, seed)
    no_official_markets = score_fitted_arm(
        scored,
        no_official_fit,
        no_official_arm.feature_columns,
        split.train,
        grouped,
        no_official_arm.name,
    )

    official_arm = Arm("official", official_feature_columns(), OFFICIAL_SOURCE_RULE)
    official_fit = fit_arm(split.train, official_arm.feature_columns, seed)
    official_used = _official_columns_used(official_fit)
    official_markets: dict[str, dict[str, object]] | None
    official_status = "measured"
    official_reason: str | None = None
    official_scored: int | None = len(scored)
    if coverage_rows == 0 or not official_used:
        official_status = "not_measurable"
        official_reason = GATED_TEXT if coverage_rows == 0 else DROPPED_TEXT
        official_markets = None
        official_scored = None
    else:
        official_markets = score_fitted_arm(
            scored,
            official_fit,
            official_arm.feature_columns,
            split.train,
            grouped,
            official_arm.name,
        )

    standin_arm = Arm("boxscore_standin", standin_feature_columns(), STANDIN_SOURCE_RULE)
    standin_status = "not_measurable"
    standin_reason = (
        "not measurable: no stand-in export. "
        "Pass --standin-dataset from build_dataset --absence-source actual."
    )
    standin_fit: FittedBaseline | None = None
    standin_markets: dict[str, dict[str, object]] | None = None
    standin_scored: int | None = None
    if standin is not None:
        standin_index = _index_standin(standin)
        if not _standin_covers(standin_index, (split.train, scored)):
            standin_reason = "not measurable: stand-in export does not cover every training or scored row"
        else:
            train_view = attach_standin_features(split.train, standin_index)
            score_view = attach_standin_features(scored, standin_index)
            standin_fit = fit_arm(train_view, standin_arm.feature_columns, seed)
            standin_markets = score_fitted_arm(
                score_view,
                standin_fit,
                standin_arm.feature_columns,
                train_view,
                grouped,
                standin_arm.name,
            )
            standin_status = "measured"
            standin_reason = None
            standin_scored = len(scored)

    naive_arm = Arm("naive_last10", (), NAIVE_SOURCE_RULE)
    naive_markets = score_naive_arm(scored, split.train, grouped)

    measured_keys: dict[str, tuple[tuple[object, ...], ...]] = {
        "no_official": scored_keys,
        "naive_last10": scored_keys,
    }
    if official_markets is not None:
        measured_keys["official"] = scored_keys
    if standin_markets is not None:
        measured_keys["boxscore_standin"] = scored_keys
    assert_same_scored_rows(measured_keys)

    code, recommendation = decide(
        coverage_rows,
        official_markets,
        no_official_markets,
        len(scored),
    )
    points_model = no_official_fit.models["player_points"]
    train_seasons = _season_list(split.train)
    validation_seasons = _season_list(split.validation)
    selection_seasons = _season_list(scored)
    used_later = any(season >= EXCLUDED_SEASON for season in train_seasons + selection_seasons)
    if used_later:
        raise AblationError("season 2026-27 was used for training or selection")
    rows = _row_counts(split, int(len(dataset)))
    rows["scored_rows"] = int(len(scored))
    rows["validation_rows_excluded_from_scoring"] = int(len(split.validation) - len(scored))
    return {
        "ticket": "SPO-155",
        "builds_on": "SPO-159 PR 137, then SPO-158, SPO-153, and SPO-154",
        "question": "Do the official T-time injury features improve the SPO-158 baseline?",
        "recommendation_code": code,
        "recommendation": recommendation,
        "production_model_changed": False,
        "official_features_in_production_model": False,
        "quantile_models": False,
        "pinball_note": PINBALL_NOTE,
        "library": "scikit-learn",
        "library_version": sklearn.__version__,
        "python_version": sys.version.split()[0],
        "seed": seed,
        "ran_against_database": False,
        "dataset_kind_note": (
            "Numbers come from the rows passed to this command. "
            "This process did not query a database."
        ),
        "pregame_export_command": DOCUMENTED_PREGAME_EXPORT,
        "standin_export_command": DOCUMENTED_STANDIN_EXPORT,
        "command": DOCUMENTED_COMMAND,
        "official_value_columns": list(official_value_columns()),
        "source_locks_not_features": list(OFFICIAL_INJURY_COLUMNS),
        "official_coverage": {
            "validation_rows": int(len(split.validation)),
            "rows_with_any_official_value": coverage_rows,
            "train_rows": int(len(split.train)),
            "train_rows_with_any_official_value": train_coverage,
        },
        "split": {
            "train_rule": TRAIN_RULE,
            "train_season": 2024,
            "train_season_name": "2024-25",
            "validation_season": 2025,
            "validation_season_name": "2025-26",
            "excluded_season": 2026,
            "excluded_season_name": "2026-27",
            "headline_info_source": "pregame",
            "headline_season_type": "regular_season",
            "validation_used_for": "the comparison only, and only on the shared naive rows",
            "train_seasons_present": train_seasons,
            "validation_seasons_present": validation_seasons,
            "selection_seasons_present": selection_seasons,
            "season_2026_27_used_for_training_or_selection": used_later,
        },
        "scored_row_rule": SCORED_ROW_RULE,
        "scored_row_count": int(len(scored)),
        "rows": rows,
        "hyperparameters": {
            "regressor": _params(REGRESSOR_PARAMS, seed),
            "classifier": _params(CLASSIFIER_PARAMS, seed),
            "iterations_run": int(points_model.n_iter_),  # type: ignore[attr-defined]
            "selection": "none. Hyperparameters are fixed. The validation season does not pick them.",
        },
        "arms": {
            "official": _arm_payload(
                official_arm,
                status=official_status,
                reason=official_reason,
                fitted=official_fit,
                markets=official_markets,
                coverage_rows=coverage_rows,
                validation_rows=int(len(split.validation)),
                scored_rows=official_scored,
            ),
            "no_official": _arm_payload(
                no_official_arm,
                status="measured",
                reason=None,
                fitted=no_official_fit,
                markets=no_official_markets,
                coverage_rows=coverage_rows,
                validation_rows=int(len(split.validation)),
                scored_rows=int(len(scored)),
            ),
            "boxscore_standin": _arm_payload(
                standin_arm,
                status=standin_status,
                reason=standin_reason,
                fitted=standin_fit,
                markets=standin_markets,
                coverage_rows=coverage_rows,
                validation_rows=int(len(split.validation)),
                scored_rows=standin_scored,
            ),
            "naive_last10": _arm_payload(
                naive_arm,
                status="measured",
                reason=None,
                fitted=None,
                markets=naive_markets,
                coverage_rows=coverage_rows,
                validation_rows=int(len(split.validation)),
                scored_rows=int(len(scored)),
            ),
        },
    }


def render_report(payload: Mapping[str, object]) -> str:
    """Render a short markdown report. It has no player rows."""
    coverage = payload["official_coverage"]
    if not isinstance(coverage, dict):
        raise AblationError("official coverage is missing")
    lines = [
        "# SPO-155 injury-feature ablation",
        "",
        str(payload["recommendation"]),
        "",
        (
            f"Official coverage: {coverage['rows_with_any_official_value']} of "
            f"{coverage['validation_rows']} validation rows have a non-missing official injury value."
        ),
        "",
        str(payload["pinball_note"]),
        "",
        f"Shared scored rows: {payload['scored_row_count']}. {payload['scored_row_rule']}",
        "",
    ]
    arms = payload["arms"]
    if not isinstance(arms, dict):
        raise AblationError("arms are missing")
    for name, arm in arms.items():
        if not isinstance(arm, dict):
            continue
        lines.append(f"## {name}")
        lines.append("")
        lines.append(f"Status: {arm['status']}.")
        if arm.get("reason"):
            lines.append(str(arm["reason"]))
        lines.append(
            f"Official coverage: {arm['official_coverage_rows']} of {arm['validation_rows']} validation rows."
        )
        markets = arm.get("markets")
        if not isinstance(markets, dict):
            lines.append("")
            continue
        for market, block in markets.items():
            if not isinstance(block, dict):
                continue
            if block.get("task") == "regression":
                lines.append(
                    f"- {name} {market} MAE {block['mae']} on {block['mae_row_count']} rows; "
                    f"pinball q=0.5 {block['pinball']} on {block['pinball_row_count']} rows."
                )
            else:
                lines.append(
                    f"- {name} {market} Brier {block['brier']} on {block['brier_row_count']} rows; "
                    f"log loss {block['log_loss']} on {block['log_loss_row_count']} rows."
                )
        lines.append("")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    """Return the CLI parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.ml.ablation_injury",
        description=(
            "Compare the pregame baseline with and without official injury features. "
            "The box-score stand-in is a separate export."
        ),
    )
    parser.add_argument("--dataset", required=True, type=Path, help="Pregame Parquet or JSON rows.")
    parser.add_argument(
        "--standin-dataset",
        type=Path,
        default=None,
        help="Box-score stand-in export (--absence-source actual). Optional.",
    )
    parser.add_argument(
        "--lines",
        type=Path,
        default=None,
        help="JSON prop lines for grading. Omit when no lines are available.",
    )
    parser.add_argument("--out", required=True, type=Path, help="Ablation JSON path.")
    parser.add_argument("--report", type=Path, default=None, help="Optional markdown report path.")
    parser.add_argument("--seed", type=int, default=SEED, help="Model seed. Default: 158.")
    return parser


def _summary_line(payload: Mapping[str, object]) -> str:
    return str(payload["recommendation"])


def main(argv: list[str] | None = None) -> int:
    """CLI entry. Returns 0 on a finished ablation and 1 on a data error."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        dataset = load_dataset(args.dataset)
        if args.standin_dataset is not None:
            standin = load_dataset(args.standin_dataset)
        else:
            standin = load_embedded_standin(args.dataset)
        lines = load_prop_lines(args.lines)
        payload = run_ablation(dataset, standin, lines, seed=args.seed)
        write_metrics(payload, args.out)
        if args.report is not None:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(render_report(payload), encoding="utf-8")
    except (AblationError, BaselineError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(_summary_line(payload))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
