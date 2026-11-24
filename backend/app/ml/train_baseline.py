"""Train the pregame baseline and write aggregate metrics.

One row is one player-game from the dataset export. The model predicts the
stat (``y_<market>``). It does not read prop lines as features. Lines, when
a JSON file is passed, are used only to grade a row, and only when
``snapshot_at <=`` that row's T.

Run from ``backend/``::

    DATABASE_URL="" python -m app.ml.train_baseline \\
        --dataset tests/fixtures/spo158/synthetic_player_games.json \\
        --lines tests/fixtures/spo158/synthetic_prop_lines.json \\
        --out ../docs/decisions/SPO-158/baseline_metrics.json

A Parquet file from ``python -m app.ml.build_dataset`` is the same kind of
input. This command does not open a database, does not write the
``predictions`` table, and does not import the API.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

from app.ml.baseline import (
    BINARY_MARKETS,
    SEED,
    SPLIT_SIDE,
    SPLIT_VALIDATION,
    SUM_MARKETS,
    T_RULE_TEXT,
    BaselineError,
    DatasetSplit,
    PropLine,
    assert_seasons_for_fit,
    excluded_feature_names,
    feature_matrix,
    headline_feature_names,
    index_prop_lines,
    label_column,
    line_values_for_frame,
    naive_column,
    parse_prop_line,
    positive_rate,
    score_probability,
    score_regression,
    split_dataset,
)

logger = logging.getLogger(__name__)

DOCUMENTED_COMMAND = (
    "DATABASE_URL=\"\" python -m app.ml.train_baseline "
    "--dataset tests/fixtures/spo158/synthetic_player_games.json "
    "--lines tests/fixtures/spo158/synthetic_prop_lines.json "
    "--out ../docs/decisions/SPO-158/baseline_metrics.json"
)

# sklearn defaults, with early stopping forced off. "auto" would hold out
# part of a large training season. The 2025-26 season is never passed to fit.
REGRESSOR_PARAMS: dict[str, object] = {
    "loss": "squared_error",
    "learning_rate": 0.1,
    "max_iter": 100,
    "max_leaf_nodes": 31,
    "min_samples_leaf": 20,
    "l2_regularization": 0.0,
    "early_stopping": False,
}
CLASSIFIER_PARAMS: dict[str, object] = {
    "learning_rate": 0.1,
    "max_iter": 100,
    "max_leaf_nodes": 31,
    "min_samples_leaf": 20,
    "l2_regularization": 0.0,
    "early_stopping": False,
}


def _params(base: Mapping[str, object], seed: int) -> dict[str, object]:
    values = dict(base)
    values["random_state"] = seed
    return values


def load_dataset(path: Path) -> pd.DataFrame:
    """Load a dataset export.

    ``.parquet`` is the file ``build_dataset`` writes. ``.json`` is a list
    of row objects, or an object with a ``rows`` list. The JSON form is the
    checked-in synthetic fixture. This function does not open a database.

    Raises:
        BaselineError: the suffix is not ``.parquet`` or ``.json``, or the
            JSON is not a list of rows.
    """
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload["rows"] if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise BaselineError("dataset JSON must be a list of rows")
        return pd.DataFrame(rows)
    raise BaselineError("dataset must be a .parquet or .json file")


def load_prop_lines(path: Path | None) -> list[PropLine]:
    """Load grade lines. ``None`` means every row has no line.

    The file is a JSON list. A post-T row may be present; grading drops it.
    The file is not joined onto the feature matrix.

    Raises:
        BaselineError: the JSON is not a list, or one object is not a line.
    """
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["lines"] if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise BaselineError("lines JSON must be a list")
    return [parse_prop_line(row) for row in rows]


def fit_baseline(train: pd.DataFrame, seed: int) -> dict[str, object]:
    """Fit one model per catalog market on ``train`` only.

    Sum-rule markets use ``HistGradientBoostingRegressor``. Double-double
    and triple-double use ``HistGradientBoostingClassifier``. The validation
    season is not an argument. Season 2026 and a non-pregame row are refused.

    Args:
        train: Headline training rows (season 2024, regular season, pregame).
        seed: ``random_state`` for every model.

    Returns:
        A map of market name to the fitted estimator.

    Raises:
        BaselineError: the season or the source is not the headline train
            set, a sum-rule market has no labeled rows, or a yes/no market
            has only one class.
    """
    if train.empty:
        raise BaselineError("the training split has no rows")
    assert_seasons_for_fit(train["season"].tolist(), role="training")
    if not (train["info_source"].astype(str) == "pregame").all():
        raise BaselineError("training rows must be info_source pregame")
    if not (train["season_type"].astype(str) == "regular_season").all():
        raise BaselineError("training rows must be regular_season")
    matrix, _names = feature_matrix(train)
    fitted: dict[str, object] = {}
    for market in SUM_MARKETS:
        y = label_column(train, market)
        mask = ~np.isnan(y)
        if int(mask.sum()) == 0:
            raise BaselineError(f"{market} has no training labels")
        model = HistGradientBoostingRegressor(**_params(REGRESSOR_PARAMS, seed))
        model.fit(matrix[mask], y[mask])
        fitted[market] = model
    for market in BINARY_MARKETS:
        y = label_column(train, market)
        mask = ~np.isnan(y)
        classes = {int(value) for value in y[mask].tolist()}
        if classes != {0, 1}:
            raise BaselineError(f"{market} training labels must include both 0 and 1")
        model = HistGradientBoostingClassifier(**_params(CLASSIFIER_PARAMS, seed))
        model.fit(matrix[mask], y[mask].astype(int))
        fitted[market] = model
    return fitted


def _predict_regression(model: object, matrix: np.ndarray) -> np.ndarray:
    predicted = model.predict(matrix)  # type: ignore[attr-defined]
    return np.asarray(predicted, dtype=np.float64)


def _predict_probability(model: object, matrix: np.ndarray) -> np.ndarray:
    probabilities = model.predict_proba(matrix)  # type: ignore[attr-defined]
    classes = [int(value) for value in model.classes_]  # type: ignore[attr-defined]
    if 1 not in classes:
        raise BaselineError("classifier has no class 1")
    column = classes.index(1)
    return np.asarray(probabilities[:, column], dtype=np.float64)


def _score_frame(
    frame: pd.DataFrame,
    models: Mapping[str, object],
    grouped_lines: Mapping[tuple[str, int, int, str], Sequence[PropLine]],
    train: pd.DataFrame,
    split_name: str,
) -> dict[str, dict[str, object]]:
    if frame.empty:
        return {}
    matrix, _names = feature_matrix(frame)
    markets: dict[str, dict[str, object]] = {}
    for market in SUM_MARKETS:
        markets[market] = score_regression(
            split=split_name,
            y=label_column(frame, market),
            predicted=_predict_regression(models[market], matrix),
            naive=naive_column(frame, market),
            lines=line_values_for_frame(frame, grouped_lines, market),
        )
    for market in BINARY_MARKETS:
        markets[market] = score_probability(
            split=split_name,
            y=label_column(frame, market),
            probability=_predict_probability(models[market], matrix),
            train_rate=positive_rate(label_column(train, market)),
            lines=line_values_for_frame(frame, grouped_lines, market),
        )
    return markets


def _row_counts(split: DatasetSplit, input_rows: int) -> dict[str, int]:
    return {
        "input_rows": input_rows,
        "train_rows": int(len(split.train)),
        "validation_rows_in_split": int(len(split.validation)),
        "side_rows_not_used_for_selection": int(len(split.side)),
        "excluded_season_2026_rows": int(len(split.excluded_season_2026)),
        "excluded_not_pregame_rows": int(len(split.excluded_not_pregame)),
        "ignored_other_rows": int(len(split.ignored_other)),
    }


def _season_used(frame: pd.DataFrame) -> list[int]:
    if frame.empty:
        return []
    return sorted({int(value) for value in frame["season"].tolist()})


def train_and_score(
    dataset: pd.DataFrame,
    lines: Sequence[PropLine],
    seed: int = SEED,
) -> dict[str, object]:
    """Fit on the training season and score the validation season.

    The side table is scored with the already fitted model. Its numbers are
    not read back into the fit. Real-database metrics stay ``PENDING``
    because this function never opens a database: the caller passes rows.

    Args:
        dataset: One player-game per row, in the export's column layout.
        lines: Grade lines. Post-T rows may be included; they are dropped
            per row inside the scorer.
        seed: Model seed. The synthetic card uses 158.

    Returns:
        The metrics dict written to ``--out``.

    Raises:
        BaselineError: the split or the fit breaks a season or feature rule.
    """
    import sklearn

    split = split_dataset(dataset)
    models = fit_baseline(split.train, seed)
    grouped = index_prop_lines(lines)
    validation = _score_frame(split.validation, models, grouped, split.train, SPLIT_VALIDATION)
    side = _score_frame(split.side, models, grouped, split.train, SPLIT_SIDE)
    points_model = models["player_points"]
    train_seasons = _season_used(split.train)
    validation_seasons = _season_used(split.validation)
    used_later = any(season >= 2026 for season in train_seasons + validation_seasons)
    features = list(headline_feature_names())
    return {
        "ticket": "SPO-158",
        "model": "baseline_no_official_injury",
        "library": "scikit-learn",
        "library_version": sklearn.__version__,
        "python_version": sys.version.split()[0],
        "seed": seed,
        "command": DOCUMENTED_COMMAND,
        "t_rule": T_RULE_TEXT,
        "t_column": "as_of",
        "ran_against_database": False,
        "real_database_metrics": "PENDING",
        "dataset_kind_note": (
            "Numbers in this file come from the rows passed to the trainer. "
            "This process did not query a database. A history-database run is PENDING."
        ),
        "split": {
            "train_season": 2024,
            "train_season_name": "2024-25",
            "validation_season": 2025,
            "validation_season_name": "2025-26",
            "excluded_season": 2026,
            "excluded_season_name": "2026-27",
            "headline_info_source": "pregame",
            "headline_season_type": "regular_season",
            "validation_used_for": "reporting_only",
            "train_seasons_present": train_seasons,
            "validation_seasons_present": validation_seasons,
            "season_2026_27_used_for_training_or_selection": used_later,
        },
        "rows": _row_counts(split, int(len(dataset))),
        "features": features,
        "feature_count": len(features),
        "excluded_features": list(excluded_feature_names()),
        "hyperparameters": {
            "regressor": _params(REGRESSOR_PARAMS, seed),
            "classifier": _params(CLASSIFIER_PARAMS, seed),
            "iterations_run": int(points_model.n_iter_),  # type: ignore[attr-defined]
            "selection": "none. Hyperparameters are fixed. The validation season is not searched.",
        },
        "markets": validation,
        "side_table_not_used_for_selection": {
            "not_used_for_selection": True,
            "split": SPLIT_SIDE,
            "row_count": int(len(split.side)),
            "markets": side,
        },
    }


def _json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (np.floating, float)):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def write_metrics(payload: Mapping[str, object], path: Path) -> None:
    """Write the metrics JSON. Parent directories are created."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_json_ready(payload), indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    """Return the CLI parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.ml.train_baseline",
        description=(
            "Fit the pregame baseline on season 2024 and score season 2025. "
            "Prop lines are optional and are used only for grading."
        ),
    )
    parser.add_argument("--dataset", required=True, type=Path, help="Parquet export or JSON rows.")
    parser.add_argument(
        "--lines",
        type=Path,
        default=None,
        help="JSON prop lines for grading. Omit when no lines are available.",
    )
    parser.add_argument("--out", required=True, type=Path, help="Metrics JSON path.")
    parser.add_argument("--seed", type=int, default=SEED, help="Model seed. Default: 158.")
    return parser


def _summary_line(metrics: Mapping[str, object]) -> str:
    markets = metrics["markets"]
    if not isinstance(markets, dict) or "player_points" not in markets:
        return "no player_points validation rows"
    points = markets["player_points"]
    if not isinstance(points, dict):
        return "no player_points validation rows"
    return (
        f"player_points {points['split']} MAE {points['mae']} "
        f"on {points['mae_row_count']} rows; "
        f"lines {points['rows_with_usable_line']}/{points['rows_scored']}; "
        f"hit rate {points['hit_rate']} on {points['hit_rate_row_count']} rows; "
        "real-database metrics PENDING"
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry. Returns 0 on success and 1 on a data error."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        dataset = load_dataset(args.dataset)
        lines = load_prop_lines(args.lines)
        metrics = train_and_score(dataset, lines, seed=args.seed)
        write_metrics(metrics, args.out)
    except (BaselineError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(_summary_line(metrics))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
