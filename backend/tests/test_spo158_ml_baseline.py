"""SPO-158 pregame baseline: leak guards and a hand-checked synthetic run.

The fixture is small on purpose. ``min_samples_leaf`` is 20 and the training
split has 4 rows, so the trees do not split. Each model predicts its training
mean. Those means are 20 for a single stat, 0.5 for double-double, and 0.25
for triple-double. The expected MAE and hit rate below are that mean scored
against the validation labels, not a second copy of the trainer.
"""

from __future__ import annotations

import inspect
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from app.ml.baseline import (
    SPLIT_VALIDATION,
    BaselineError,
    PropLine,
    assert_headline_feature_list,
    assert_seasons_for_fit,
    feature_matrix,
    headline_feature_names,
    line_visible_at_t,
    median_line_at_t,
    naive_projection,
    score_regression,
)
from app.ml.train_baseline import fit_baseline, load_dataset, load_prop_lines, main

FIXTURE = Path(__file__).parent / "fixtures" / "spo158" / "synthetic_player_games.json"
LINES = Path(__file__).parent / "fixtures" / "spo158" / "synthetic_prop_lines.json"
METRICS = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "decisions"
    / "SPO-158"
    / "baseline_metrics_synthetic.json"
)
UTC = timezone.utc
T = datetime(2025, 11, 1, 23, 0, tzinfo=UTC)

FORBIDDEN = (
    "nba_injury_report_rows",
    "injuries_nba_official",
    "current_injuries",
    "source_covered",
    "player_prop_snapshots",
    "player_injury_status",
    "team_missing_minutes",
    "opp_missing_minutes",
    "is_starter",
    "y_player_points",
    "home_score",
)


def _line(
    book: str,
    kind: str,
    when: datetime | None,
    line: float,
    *,
    game: int = 2501,
    player: int = 10,
) -> PropLine:
    return PropLine(
        league="nba",
        bdl_game_id=game,
        bdl_player_id=player,
        book_key=book,
        market="player_points",
        snapshot_kind=kind,
        snapshot_at=when,
        line=line,
    )


def _run(tmp_path: Path, dataset: Path | None = None) -> dict[str, object]:
    out = tmp_path / "metrics.json"
    code = main(
        [
            "--dataset",
            str(dataset or FIXTURE),
            "--lines",
            str(LINES),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    return json.loads(out.read_text(encoding="utf-8"))


def test_headline_list_rejects_official_injury_and_prop_columns() -> None:
    names = headline_feature_names()
    assert "pts_last_10" in names
    assert "opening_total" in names
    assert "is_home" in names
    assert "team_missing_share_player_points" not in names
    for name in FORBIDDEN:
        assert name not in names
        with pytest.raises(BaselineError):
            assert_headline_feature_list(names + (name,))


def test_extra_injury_and_line_columns_stay_out_of_the_matrix() -> None:
    frame = load_dataset(FIXTURE)
    frame["injuries_nba_official"] = 1
    frame["player_prop_snapshots"] = 1
    frame["home_score"] = 120
    matrix, names = feature_matrix(frame)
    assert "injuries_nba_official" not in names
    assert "player_prop_snapshots" not in names
    assert "home_score" not in names
    assert matrix.shape == (len(frame), len(headline_feature_names()))


def test_line_at_exactly_t_is_visible_and_one_second_later_is_not() -> None:
    assert line_visible_at_t(T, T) is True
    assert line_visible_at_t(T - timedelta(seconds=1), T) is True
    assert line_visible_at_t(T + timedelta(seconds=1), T) is False
    assert line_visible_at_t(None, T) is False


def test_null_timestamp_is_excluded_not_imputed() -> None:
    lines = (
        _line("draftkings", "opening", T, 10.0),
        _line("betmgm", "opening", None, 40.0),
    )
    assert median_line_at_t(lines, as_of=T) == 10.0


def test_post_t_line_is_excluded_from_the_median() -> None:
    """The grade line is 9.5. The live 100 posted one second after T is not in it."""
    lines = load_prop_lines(LINES)
    game = [row for row in lines if row.bdl_game_id == 2501 and row.bdl_player_id == 10]
    assert median_line_at_t(game, as_of=T) == 9.5


def test_latest_pre_t_line_per_book_is_the_one_that_counts() -> None:
    as_of = datetime(2025, 11, 5, 23, 0, tzinfo=UTC)
    lines = load_prop_lines(LINES)
    game = [row for row in lines if row.bdl_game_id == 2505 and row.bdl_player_id == 10]
    assert median_line_at_t(game, as_of=as_of) == 25.0


def test_a_line_after_t_only_counts_as_missing() -> None:
    as_of = datetime(2025, 11, 7, 23, 0, tzinfo=UTC)
    lines = load_prop_lines(LINES)
    game = [row for row in lines if row.bdl_game_id == 2507]
    assert median_line_at_t(game, as_of=as_of) is None


def test_naive_uses_last_5_when_last_10_is_null() -> None:
    assert naive_projection({"pts_last_10": None, "pts_last_5": 16}, "player_points") == 16
    assert naive_projection({"pts_last_10": 10, "pts_last_5": 16}, "player_points") == 10
    assert naive_projection({"pts_last_10": None, "pts_last_5": None}, "player_points") is None
    combo = {
        "pts_last_10": None,
        "pts_last_5": None,
        "reb_last_10": 4,
        "reb_last_5": 4,
    }
    assert naive_projection(combo, "player_points_rebounds") is None


def test_missing_line_stays_in_the_mae_denominator() -> None:
    scored = score_regression(
        split="hand",
        y=np.array([12.0, 10.0, 12.0, 8.0]),
        predicted=np.array([11.0, 11.0, 9.0, 8.0]),
        naive=np.array([12.0, 10.0, 12.0, 8.0]),
        lines=np.array([10.0, 10.0, 10.0, np.nan]),
    )
    assert scored["rows_scored"] == 4
    assert scored["rows_with_usable_line"] == 3
    assert scored["rows_without_line"] == 1
    assert scored["rows_scored"] == scored["rows_with_usable_line"] + scored["rows_without_line"]
    assert scored["mae"] == pytest.approx(1.25)
    assert scored["mae_row_count"] == 4
    assert scored["naive_last10_mae"] == 0
    assert scored["hits"] == 1
    assert scored["misses"] == 1
    assert scored["pushes"] == 1
    assert scored["hit_rate_row_count"] == 2
    assert scored["hit_rate"] == pytest.approx(0.5)
    assert scored["hit_rate_row_count"] < scored["rows_scored"]


def test_a_prediction_on_the_line_is_not_called_a_hit() -> None:
    scored = score_regression(
        split="hand",
        y=np.array([12.0]),
        predicted=np.array([10.0]),
        naive=np.array([12.0]),
        lines=np.array([10.0]),
    )
    assert scored["prediction_on_line"] == 1
    assert scored["hits"] == 0
    assert scored["hit_rate_row_count"] == 0
    assert scored["hit_rate"] is None
    assert scored["rows_with_usable_line"] == 1


def test_season_2026_cannot_be_used_to_fit_or_select() -> None:
    with pytest.raises(BaselineError, match="2026"):
        assert_seasons_for_fit([2024, 2026], role="training")
    with pytest.raises(BaselineError, match="2026"):
        assert_seasons_for_fit([2026], role="validation")


def test_fit_does_not_take_the_validation_season() -> None:
    names = set(inspect.signature(fit_baseline).parameters)
    assert "validation" not in names
    assert "valid" not in names
    frame = load_dataset(FIXTURE)
    future = frame.loc[frame["season"] == 2026].reset_index(drop=True)
    with pytest.raises(BaselineError, match="2026"):
        fit_baseline(future, 158)


def test_synthetic_run_matches_the_hand_calculation(tmp_path: Path) -> None:
    metrics = _run(tmp_path)
    assert metrics["real_database_metrics"] == "PENDING"
    assert metrics["ran_against_database"] is False
    assert metrics["split"]["season_2026_27_used_for_training_or_selection"] is False
    assert metrics["split"]["train_seasons_present"] == [2024]
    assert metrics["split"]["validation_seasons_present"] == [2025]
    assert metrics["split"]["validation_used_for"] == "reporting_only"
    assert metrics["rows"]["input_rows"] == 17
    assert metrics["rows"]["train_rows"] == 4
    assert metrics["rows"]["validation_rows_in_split"] == 9
    assert metrics["rows"]["excluded_season_2026_rows"] == 1
    assert metrics["rows"]["excluded_not_pregame_rows"] == 1
    assert metrics["rows"]["ignored_other_rows"] == 1
    assert metrics["rows"]["side_rows_not_used_for_selection"] == 1
    assert metrics["hyperparameters"]["iterations_run"] == 100
    assert metrics["hyperparameters"]["regressor"]["early_stopping"] is False
    assert metrics["hyperparameters"]["regressor"]["min_samples_leaf"] == 20
    assert metrics["features"] == list(headline_feature_names())
    assert metrics["feature_count"] == 28
    assert metrics["features_dropped_all_missing_in_train"] == []
    assert metrics["features_actually_fit"] == metrics["features"]

    points = metrics["markets"]["player_points"]
    assert points["split"] == SPLIT_VALIDATION
    assert points["rows_in_split"] == 9
    assert points["rows_scored"] == 8
    assert points["rows_label_null"] == 1
    assert points["rows_with_usable_line"] == 4
    assert points["rows_without_line"] == 4
    assert points["mae"] == 9.25
    assert points["mae_row_count"] == 8
    assert points["naive_last10_mae"] == 2.5
    assert points["naive_row_count"] == 8
    assert points["hits"] == 2
    assert points["misses"] == 1
    assert points["pushes"] == 1
    assert points["prediction_on_line"] == 0
    assert points["hit_rate_row_count"] == 3
    assert points["hit_rate"] == pytest.approx(2 / 3)
    assert points["hit_rate_row_count"] < points["rows_scored"]
    bins = {item["bin"]: item for item in points["calibration"]["bins"]}
    assert bins["below_-5"]["row_count"] == 3
    assert bins["within_5"]["row_count"] == 1
    assert bins["above_5"]["row_count"] == 4

    rebounds = metrics["markets"]["player_rebounds"]
    assert rebounds["mae"] == 9.25
    assert rebounds["mae_row_count"] == 8
    assert rebounds["naive_last10_mae"] == 0
    assert rebounds["rows_with_usable_line"] == 0
    assert rebounds["rows_without_line"] == 8
    assert rebounds["hit_rate"] is None

    double = metrics["markets"]["player_double_double"]
    assert double["brier"] == 0.25
    assert double["brier_row_count"] == 8
    assert double["log_loss"] == pytest.approx(math.log(2))
    assert double["naive_train_rate"] == 0.5
    assert double["rows_without_line"] == 8
    band = next(item for item in double["calibration"]["bins"] if item["bin_low"] == 0.4)
    assert band["row_count"] == 8
    assert band["mean_outcome"] == pytest.approx(3 / 8)

    triple = metrics["markets"]["player_triple_double"]
    assert triple["brier"] == 0.0625
    assert triple["brier_row_count"] == 8
    assert triple["log_loss"] == pytest.approx(-math.log(0.75))
    assert triple["naive_train_rate"] == 0.25

    for market, block in metrics["markets"].items():
        assert block["split"] == SPLIT_VALIDATION
        assert block["rows_scored"] == block["rows_with_usable_line"] + block["rows_without_line"]
        assert "rows_label_null" in block
        if market in {"player_double_double", "player_triple_double"}:
            assert block["task"] == "probability"
            assert "brier" in block
        else:
            assert block["task"] == "regression"
            assert "mae" in block
            assert "naive_last10_mae" in block

    side = metrics["side_table_not_used_for_selection"]
    assert side["not_used_for_selection"] is True
    assert side["row_count"] == 1
    assert side["markets"]["player_points"]["mae"] == 10
    assert side["markets"]["player_points"]["rows_scored"] == 1
    # The exclusion list may name the column. The scored markets must not
    # carry a per-player dump.
    assert "bdl_player_id" not in json.dumps(metrics["markets"])
    assert "bdl_player_id" not in json.dumps(side["markets"])


def test_a_parquet_export_scores_the_same_as_the_json_fixture(tmp_path: Path) -> None:
    frame = load_dataset(FIXTURE)
    parquet = tmp_path / "player_games.parquet"
    frame.to_parquet(parquet, index=False)
    from_json = _run(tmp_path / "json")
    from_parquet = _run(tmp_path / "parquet", dataset=parquet)
    assert from_parquet["markets"]["player_points"] == from_json["markets"]["player_points"]


def test_committed_metrics_file_matches_a_fresh_run(tmp_path: Path) -> None:
    fresh = _run(tmp_path)
    committed = json.loads(METRICS.read_text(encoding="utf-8"))
    assert committed["real_database_metrics"] == "PENDING"
    assert committed["markets"]["player_points"]["mae"] == 9.25
    assert committed["markets"]["player_points"]["rows_scored"] == 8
    assert committed["markets"]["player_points"]["rows_with_usable_line"] == 4
    assert committed["markets"]["player_points"]["rows_without_line"] == 4
    assert committed["markets"]["player_points"]["hit_rate_row_count"] == 3
    assert committed["split"]["season_2026_27_used_for_training_or_selection"] is False
    assert committed["markets"]["player_points"] == fresh["markets"]["player_points"]
    assert committed["rows"] == fresh["rows"]
    assert committed["features"] == fresh["features"]
    assert committed["features_dropped_all_missing_in_train"] == []
    assert committed["features_actually_fit"] == committed["features"]


def test_trainer_source_does_not_open_the_history_database() -> None:
    backend = Path(__file__).resolve().parents[1]
    for name in ("app/ml/train_baseline.py", "app/ml/baseline.py"):
        text = (backend / name).read_text(encoding="utf-8")
        assert "127.0.0.1:5434" not in text
        assert "asyncpg" not in text
        assert "INSERT" not in text.upper()
    assert "sklearn" not in (backend / "app/ml/baseline.py").read_text(encoding="utf-8")


def test_importing_the_trainer_does_not_import_injury_ingest() -> None:
    """A fresh process imports the trainer. Earlier tests may already have
    loaded the injury modules into this process, so ``sys.modules`` here
    cannot prove what the trainer itself imports.
    """
    backend = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["DATABASE_URL"] = ""
    env.pop("ML_DATABASE_URL", None)
    script = (
        "import app.ml.train_baseline, sys; "
        "names = ("
        "'app.services.injury_report_ingest', "
        "'app.services.injury_report_parser'"
        "); "
        "bad = [name for name in names if name in sys.modules]; "
        "print(bad); "
        "raise SystemExit(1 if bad else 0)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_importing_the_api_does_not_import_app_ml() -> None:
    backend = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["DATABASE_URL"] = ""
    env.pop("ML_DATABASE_URL", None)
    script = (
        "import app.main, sys; "
        "bad = [name for name in sys.modules if name == 'app.ml' or name.startswith('app.ml.')]; "
        "raise SystemExit(1 if bad else 0)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
