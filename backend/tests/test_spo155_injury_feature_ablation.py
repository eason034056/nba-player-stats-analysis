"""SPO-155 ablation of official injury features against the SPO-158 baseline.

The fixtures are made up. A row is one fake player-game. Official coverage
of zero must not be reported as a gain. A 2026-27 row must not be fit or
used to pick the recommendation. Stand-in numbers must not sit in the
official count columns.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from app.ml.ablation_injury import (
    GATED_TEXT,
    PLAYER_P_OUT,
    AblationError,
    assert_frame_allowed,
    assert_same_scored_rows,
    decide,
    main,
    run_ablation,
)
from app.ml.absence import (
    ABSENCE_FEATURE_COLUMNS,
    COVERAGE_NOTE_PRESENT,
    OFFICIAL_COUNT_COLUMNS,
    SOURCE_ACTUAL,
)
from app.ml.baseline import BINARY_MARKETS, SUM_MARKETS, headline_feature_names
from app.ml.build_dataset import (
    IDENTITY_COLUMNS,
    OUTPUT_COLUMNS,
    assemble_dataset,
    build_parser,
    write_outputs,
)
from app.ml.features import COUNT_COLUMNS, form_column_names
from app.ml.game_odds import ODDS_COLUMNS
from app.ml.labels import label_column_names
from app.ml.train_baseline import load_dataset, load_prop_lines, train_and_score

FIXTURE = Path(__file__).parent / "fixtures" / "spo155"
SIGNAL = FIXTURE / "signal_pregame.json"
STANDIN = FIXTURE / "signal_standin.json"
ZERO = FIXTURE / "zero_coverage_pregame.json"
SPO158 = Path(__file__).parent / "fixtures" / "spo158" / "synthetic_player_games.json"
SPO158_LINES = Path(__file__).parent / "fixtures" / "spo158" / "synthetic_prop_lines.json"


def _market_block(task: str, *, mae: float | None = None, brier: float | None = None, rows: int = 10) -> dict[str, object]:
    if task == "regression":
        return {"task": "regression", "mae": mae, "mae_row_count": rows, "brier": brier, "brier_row_count": rows}
    return {"task": "probability", "mae": mae, "mae_row_count": rows, "brier": brier, "brier_row_count": rows}


def _markets(*, points_mae: float, dd_brier: float, other_mae: float, other_brier: float, rows: int = 10) -> dict[str, dict[str, object]]:
    markets: dict[str, dict[str, object]] = {}
    for market in SUM_MARKETS:
        mae = points_mae if market == "player_points" else other_mae
        markets[market] = _market_block("regression", mae=mae, rows=rows)
    for market in BINARY_MARKETS:
        brier = dd_brier if market == "player_double_double" else other_brier
        markets[market] = _market_block("probability", brier=brier, rows=rows)
    return markets


def test_signal_fixture_official_arm_beats_the_baseline() -> None:
    """Official minutes and status predict the label. The baseline cannot."""
    result = run_ablation(load_dataset(SIGNAL), load_dataset(STANDIN), [], seed=158)
    assert result["recommendation_code"] == "ship"
    assert result["production_model_changed"] is False
    assert result["official_features_in_production_model"] is False
    assert "Production still leaves those features off." in result["recommendation"]
    assert result["quantile_models"] is False
    assert "q=0.5 only" in str(result["pinball_note"])
    assert result["split"]["train_seasons_present"] == [2024]
    assert result["split"]["validation_seasons_present"] == [2025]
    assert result["split"]["selection_seasons_present"] == [2025]
    assert result["split"]["season_2026_27_used_for_training_or_selection"] is False
    assert result["rows"]["excluded_season_2026_rows"] == 1
    assert result["rows"]["train_rows"] == 80
    assert result["scored_row_count"] == 40
    coverage = result["official_coverage"]
    assert isinstance(coverage, dict)
    assert coverage["rows_with_any_official_value"] == 40
    assert coverage["validation_rows"] == 40
    assert "--absence-source actual" in str(result["standin_export_command"])
    assert "absence-source" not in str(result["pregame_export_command"])
    assert "nba_injury_report_rows" in result["source_locks_not_features"]
    official_columns = result["arms"]["official"]["feature_columns"]
    assert isinstance(official_columns, list)
    assert "nba_injury_report_rows" not in official_columns
    assert "rot_out_n" in official_columns
    assert "team_missing_minutes" in official_columns
    assert PLAYER_P_OUT in official_columns

    official = result["arms"]["official"]["markets"]["player_points"]
    baseline = result["arms"]["no_official"]["markets"]["player_points"]
    naive = result["arms"]["naive_last10"]["markets"]["player_points"]
    assert official["arm"] == "official"
    assert baseline["arm"] == "no_official"
    assert naive["arm"] == "naive_last10"
    assert official["mae_row_count"] == baseline["mae_row_count"] == naive["mae_row_count"] == 40
    assert official["mae"] < 0.01
    assert baseline["mae"] == 14.0
    assert naive["mae"] == 14.0
    assert official["mae"] < baseline["mae"]
    assert official["pinball_q"] == 0.5
    assert official["pinball_q25"] is None
    assert official["pinball_q75"] is None
    assert official["pinball_row_count"] == 40
    assert official["quantile_models"] is False
    assert sum(item["row_count"] for item in official["calibration"]["bins"]) == 40
    assert baseline["naive_last10_mae"] == naive["mae"]
    assert baseline["naive_row_count"] == 40

    official_dd = result["arms"]["official"]["markets"]["player_double_double"]
    baseline_dd = result["arms"]["no_official"]["markets"]["player_double_double"]
    assert official_dd["arm"] == "official"
    assert official_dd["brier_row_count"] == baseline_dd["brier_row_count"] == 40
    assert official_dd["log_loss_row_count"] == 40
    assert official_dd["brier"] < baseline_dd["brier"]
    assert sum(item["row_count"] for item in official_dd["calibration"]["bins"]) == 40
    assert official_dd["pinball_q25"] is None
    assert official_dd["pinball_q75"] is None

    standin_fit = result["arms"]["boxscore_standin"]["features_actually_fit"]
    assert result["arms"]["boxscore_standin"]["status"] == "measured"
    assert not set(standin_fit) & set(OFFICIAL_COUNT_COLUMNS)
    assert result["arms"]["boxscore_standin"]["official_coverage_rows"] == 40


def test_zero_official_coverage_is_not_a_gain() -> None:
    """All-null official columns collapse the arm. That is not a win."""
    result = run_ablation(load_dataset(ZERO), load_dataset(STANDIN), [], seed=158)
    official = result["arms"]["official"]
    assert official["status"] == "not_measurable"
    assert official["markets"] is None
    assert official["reason"] == GATED_TEXT
    assert result["recommendation_code"] == "not_measurable"
    assert result["recommendation"] == GATED_TEXT
    assert "lower error" not in str(result["recommendation"])
    assert "ship:" not in str(result["recommendation"])
    coverage = result["official_coverage"]
    assert isinstance(coverage, dict)
    assert coverage["rows_with_any_official_value"] == 0
    assert coverage["train_rows_with_any_official_value"] == 0
    dropped = set(official["features_dropped_all_missing_in_train"])
    assert set(OFFICIAL_COUNT_COLUMNS) <= dropped
    assert "team_missing_minutes" in dropped
    assert PLAYER_P_OUT in dropped
    assert official["features_actually_fit"] == list(headline_feature_names())
    points = result["arms"]["no_official"]["markets"]["player_points"]
    assert points["mae"] == 14.0
    assert points["mae_row_count"] == 40
    assert points["arm"] == "no_official"
    assert result["arms"]["no_official"]["official_coverage_rows"] == 0
    assert result["arms"]["naive_last10"]["official_coverage_rows"] == 0
    assert result["production_model_changed"] is False


def test_copying_standin_values_into_official_columns_raises() -> None:
    """A stand-in minute copied into an official count column is refused."""
    standin = load_dataset(STANDIN)
    standin = standin.copy()
    standin["rot_out_n"] = standin["team_missing_minutes"]
    with pytest.raises(AblationError, match="stand-in values appear in official column rot_out_n"):
        run_ablation(load_dataset(SIGNAL), standin, [], seed=158)


def test_standin_row_inside_the_pregame_file_cannot_carry_official_counts() -> None:
    frame = load_dataset(SIGNAL)
    extra = frame.iloc[[0]].copy()
    extra["info_source"] = "standin"
    extra["rot_out_n"] = extra["team_missing_minutes"]
    mixed = pd.concat([frame, extra], ignore_index=True)
    with pytest.raises(AblationError, match="stand-in values appear in official column rot_out_n"):
        run_ablation(mixed, None, [], seed=158)


def test_season_2026_in_train_or_selection_raises() -> None:
    frame = pd.DataFrame({"season": [2024, 2026]})
    with pytest.raises(AblationError, match="2026"):
        assert_frame_allowed(frame, role="training")
    with pytest.raises(AblationError, match="2026"):
        assert_frame_allowed(pd.DataFrame({"season": [2026]}), role="selection")


def test_different_scored_row_sets_raise() -> None:
    with pytest.raises(AblationError, match="different row sets"):
        assert_same_scored_rows(
            {
                "official": (("nba", 2025, 1, 1),),
                "no_official": (("nba", 2025, 1, 2),),
            }
        )


def test_decision_rejects_different_row_counts() -> None:
    official = _markets(points_mae=1, dd_brier=0.1, other_mae=1, other_brier=0.1, rows=10)
    baseline = _markets(points_mae=2, dd_brier=0.2, other_mae=2, other_brier=0.2, rows=10)
    official["player_points"]["mae_row_count"] = 9
    with pytest.raises(AblationError, match="different row sets"):
        decide(10, official, baseline, scored_rows=10)


def test_decision_ship_some_and_dont_ship() -> None:
    mixed_official = _markets(points_mae=1, dd_brier=0.3, other_mae=5, other_brier=0.2)
    mixed_baseline = _markets(points_mae=2, dd_brier=0.1, other_mae=5, other_brier=0.2)
    code, text = decide(10, mixed_official, mixed_baseline, scored_rows=10)
    assert code == "ship_some"
    assert "player_points" in text
    assert "player_double_double" in text
    assert "10 shared validation rows" in text
    assert "Production still leaves those features off." in text

    worse = _markets(points_mae=5, dd_brier=0.2, other_mae=5, other_brier=0.2)
    better_baseline = _markets(points_mae=4, dd_brier=0.2, other_mae=5, other_brier=0.2)
    code, text = decide(10, worse, better_baseline, scored_rows=10)
    assert code == "dont_ship"
    assert "10 shared validation rows" in text

    code, text = decide(0, mixed_official, mixed_baseline, scored_rows=10)
    assert code == "not_measurable"
    assert text == GATED_TEXT
    assert "lower error" not in text


def test_spo158_fixture_keeps_the_baseline_score_and_has_no_official_coverage() -> None:
    result = run_ablation(load_dataset(SPO158), None, load_prop_lines(SPO158_LINES), seed=158)
    assert result["arms"]["official"]["status"] == "not_measurable"
    assert result["arms"]["official"]["markets"] is None
    assert result["recommendation_code"] == "not_measurable"
    assert result["official_coverage"]["rows_with_any_official_value"] == 0
    points = result["arms"]["no_official"]["markets"]["player_points"]
    assert points["mae"] == 9.25
    assert points["mae_row_count"] == 8
    assert points["rows_with_usable_line"] == 4
    assert points["arm"] == "no_official"
    assert result["arms"]["boxscore_standin"]["status"] == "not_measurable"


def test_train_baseline_ignores_official_columns_on_the_signal_fixture() -> None:
    """The production trainer still fits the locked list and misses the signal."""
    metrics = train_and_score(load_dataset(SIGNAL), [], seed=158)
    points = metrics["markets"]["player_points"]
    assert isinstance(points, dict)
    assert points["mae"] == 14.0
    assert points["mae_row_count"] == 40
    assert metrics["features"] == list(headline_feature_names())
    assert "rot_out_n" not in metrics["features"]
    assert "team_missing_minutes" not in metrics["features_actually_fit"]


def test_cli_on_the_signal_fixture_writes_aggregate_output(tmp_path: Path) -> None:
    out = tmp_path / "ablation.json"
    report = tmp_path / "ablation.md"
    code = main(
        [
            "--dataset",
            str(SIGNAL),
            "--standin-dataset",
            str(STANDIN),
            "--out",
            str(out),
            "--report",
            str(report),
        ]
    )
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["recommendation_code"] == "ship"
    assert payload["arms"]["official"]["markets"]["player_points"]["mae_row_count"] == 40
    text = report.read_text(encoding="utf-8")
    assert "official player_points MAE" in text
    assert "on 40 rows" in text
    assert "910000" not in text
    assert "bdl_player_id" not in out.read_text(encoding="utf-8")


def test_cli_on_zero_coverage_writes_the_gated_sentence(tmp_path: Path) -> None:
    out = tmp_path / "ablation.json"
    code = main(
        [
            "--dataset",
            str(ZERO),
            "--standin-dataset",
            str(STANDIN),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["recommendation"] == GATED_TEXT
    assert payload["arms"]["official"]["markets"] is None
    assert payload["official_coverage"]["rows_with_any_official_value"] == 0


def test_parquet_input_matches_the_json_signal(tmp_path: Path) -> None:
    frame = load_dataset(SIGNAL)
    path = tmp_path / "signal.parquet"
    frame.to_parquet(path, index=False)
    result = run_ablation(load_dataset(path), load_dataset(STANDIN), [], seed=158)
    assert result["recommendation_code"] == "ship"
    assert result["arms"]["official"]["markets"]["player_points"]["mae_row_count"] == 40


def test_absence_source_defaults_to_reported_and_output_columns_stay() -> None:
    """The new flag is opt-in. The default export column list is unchanged."""
    args = build_parser().parse_args(
        ["--dsn-env", "ML_DATABASE_URL", "--seasons", "2023:2025", "--out", "x.parquet"]
    )
    assert args.absence_source == "reported"
    actual = build_parser().parse_args(
        [
            "--dsn-env",
            "ML_DATABASE_URL",
            "--seasons",
            "2023:2025",
            "--out",
            "x.parquet",
            "--absence-source",
            "actual",
        ]
    )
    assert actual.absence_source == "actual"
    assert len(OUTPUT_COLUMNS) == 70
    assert OUTPUT_COLUMNS == (
        IDENTITY_COLUMNS
        + COUNT_COLUMNS
        + form_column_names()
        + ODDS_COLUMNS
        + ABSENCE_FEATURE_COLUMNS
        + ("is_starter", "player_injury_status")
        + OFFICIAL_COUNT_COLUMNS
        + label_column_names()
    )


def test_actual_export_note_does_not_say_the_absence_columns_stay_empty(tmp_path: Path) -> None:
    """A stand-in export fills minute and share columns, so its note must say so.

    The reported note stays the old sentence. Output column names do not change.
    """
    present = "source_covered is present but this export does not read its columns"
    reported = assemble_dataset(
        [],
        [],
        [],
        season_start=2024,
        season_end=2025,
        git_head="sha",
        coverage_relation_note=present,
    )
    assert reported.metadata["absence_coverage_note"] == COVERAGE_NOTE_PRESENT
    actual = assemble_dataset(
        [],
        [],
        [],
        season_start=2024,
        season_end=2025,
        git_head="sha",
        absence_source=SOURCE_ACTUAL,
        coverage_relation_note=present,
    )
    note = str(actual.metadata["absence_coverage_note"])
    assert "pregame absence features stay empty" not in note
    assert "info_source standin" in note
    assert "are filled" in note
    meta_path = write_outputs(actual, tmp_path / "standin.parquet")
    written = json.loads(meta_path.read_text(encoding="utf-8"))
    assert written["absence_coverage_note"] == note
    assert list(OUTPUT_COLUMNS) == list(
        IDENTITY_COLUMNS
        + COUNT_COLUMNS
        + form_column_names()
        + ODDS_COLUMNS
        + ABSENCE_FEATURE_COLUMNS
        + ("is_starter", "player_injury_status")
        + OFFICIAL_COUNT_COLUMNS
        + label_column_names()
    )


def test_importing_the_ablation_does_not_import_injury_ingest() -> None:
    backend = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["DATABASE_URL"] = ""
    env.pop("ML_DATABASE_URL", None)
    script = (
        "import app.ml.ablation_injury, sys; "
        "names = ("
        "'app.services.injury_report_ingest', "
        "'app.services.injury_report_parser'"
        "); "
        "bad = [name for name in names if name in sys.modules]; "
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
