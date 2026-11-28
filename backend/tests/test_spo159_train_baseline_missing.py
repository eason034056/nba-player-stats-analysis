"""SPO-159: a feature that is missing on every training row is left out of the fit.

The synthetic fixture has a number in every feature, so these tests blank
columns on a copy. The locked ``features`` list stays the full headline
set. The drop list is decided from the training split only.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.ml.baseline import BaselineError, headline_feature_names, split_dataset
from app.ml.train_baseline import (
    fit_baseline,
    load_dataset,
    load_prop_lines,
    train_and_score,
    write_metrics,
)

FIXTURE = Path(__file__).parent / "fixtures" / "spo158" / "synthetic_player_games.json"
LINES = Path(__file__).parent / "fixtures" / "spo158" / "synthetic_prop_lines.json"


def _train_mask(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["season"].astype(int).eq(2024)
        & frame["info_source"].astype(str).eq("pregame")
        & frame["season_type"].astype(str).eq("regular_season")
    )


def _validation_mask(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["season"].astype(int).eq(2025)
        & frame["info_source"].astype(str).eq("pregame")
        & frame["season_type"].astype(str).eq("regular_season")
    )


def _written(frame: pd.DataFrame, tmp_path: Path) -> dict[str, object]:
    metrics = train_and_score(frame, load_prop_lines(LINES), seed=158)
    path = tmp_path / "metrics.json"
    write_metrics(metrics, path)
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_partition(metrics: dict[str, object], dropped_name: str | None) -> None:
    features = metrics["features"]
    dropped = metrics["features_dropped_all_missing_in_train"]
    fitted = metrics["features_actually_fit"]
    assert features == list(headline_feature_names())
    assert isinstance(dropped, list)
    assert isinstance(fitted, list)
    assert [name for name in features if name in set(fitted)] == fitted
    assert [name for name in features if name not in set(fitted)] == dropped
    if dropped_name is None:
        return
    assert dropped_name in dropped
    assert dropped_name not in fitted


def test_all_nan_train_column_is_dropped_and_scoring_succeeds(tmp_path: Path) -> None:
    """Blank one feature on every training row. Fit and both scores must finish."""
    frame = load_dataset(FIXTURE)
    train = _train_mask(frame)
    assert int(train.sum()) == 4
    frame.loc[train, "opening_spread_home"] = np.nan
    assert bool(frame.loc[train, "opening_spread_home"].isna().all())
    metrics = _written(frame, tmp_path)
    _assert_partition(metrics, "opening_spread_home")
    points = metrics["markets"]["player_points"]
    assert isinstance(points, dict)
    assert points["mae"] == 9.25
    assert points["mae_row_count"] == 8
    assert points["rows_scored"] == 8
    side = metrics["side_table_not_used_for_selection"]
    assert isinstance(side, dict)
    side_points = side["markets"]["player_points"]
    assert isinstance(side_points, dict)
    assert side_points["rows_scored"] == 1
    assert side_points["mae"] == 10


def test_train_nan_column_with_validation_values_is_still_dropped(tmp_path: Path) -> None:
    """Validation numbers do not keep a column that training never saw."""
    frame = load_dataset(FIXTURE)
    train = _train_mask(frame)
    validation = _validation_mask(frame)
    assert int(validation.sum()) == 9
    frame.loc[train, "opening_total"] = np.nan
    assert bool(frame.loc[train, "opening_total"].isna().all())
    assert int(frame.loc[validation, "opening_total"].notna().sum()) == 9
    metrics = _written(frame, tmp_path)
    _assert_partition(metrics, "opening_total")
    points = metrics["markets"]["player_points"]
    assert isinstance(points, dict)
    assert points["rows_scored"] == 8
    assert points["mae"] == 9.25


def test_partly_missing_train_column_is_kept(tmp_path: Path) -> None:
    frame = load_dataset(FIXTURE)
    train_index = frame.index[_train_mask(frame)]
    assert len(train_index) == 4
    frame.loc[train_index[:1], "team_implied_points"] = np.nan
    train = frame.loc[train_index, "team_implied_points"]
    assert int(train.isna().sum()) == 1
    assert int(train.notna().sum()) == 3
    metrics = _written(frame, tmp_path)
    _assert_partition(metrics, None)
    assert "team_implied_points" in metrics["features_actually_fit"]
    assert "team_implied_points" not in metrics["features_dropped_all_missing_in_train"]
    points = metrics["markets"]["player_points"]
    assert isinstance(points, dict)
    assert points["mae_row_count"] == 8


def test_every_feature_missing_on_the_training_split_raises() -> None:
    frame = load_dataset(FIXTURE)
    train = _train_mask(frame)
    assert int(train.sum()) == 4
    for name in headline_feature_names():
        # Boolean columns cannot store NaN until they are numeric. 1 and 0
        # are the same values the matrix builder uses for True and False.
        numbers = pd.to_numeric(frame[name], errors="coerce")
        frame[name] = numbers.mask(train)
    validation = _validation_mask(frame)
    assert int(frame.loc[validation, "is_home"].notna().sum()) == 9
    with pytest.raises(BaselineError, match="every headline feature is missing"):
        train_and_score(frame, load_prop_lines(LINES), seed=158)
    split = split_dataset(frame)
    with pytest.raises(BaselineError, match="every headline feature is missing"):
        fit_baseline(split.train, 158)
