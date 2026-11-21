"""Export one Parquet row per ``player_game_stats`` row.

Run from ``backend/``::

    python -m app.ml.build_dataset \\
        --dsn-env ML_DATABASE_URL \\
        --seasons 2015:2025 \\
        --hours-before-tip 3 \\
        --out player_games.parquet

``--seasons START:END`` is inclusive: 2015 and 2025 are both written.
``--hours-before-tip`` defaults to 3. The DSN is the value of the named
environment variable and is never printed.

History loaded for features starts the season before ``START``, so the
first output season is not cut off. Every output row has
``info_source = pregame``. The file next to the Parquet is
``<file>.meta.json`` (``player_games.parquet`` -> ``player_games.meta.json``).

This command does not write ``predictions`` and does not create a feature
table. It is not imported by the API.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.ml.asof import DEFAULT_HOURS_BEFORE_TIP, T_RULE, prediction_instant
from app.ml.features import COUNT_COLUMNS, features_for_target, form_column_names
from app.ml.labels import label_column_names, pivot_labels
from app.ml.load import (
    ActualRecord,
    GameRecord,
    LoadError,
    StatRecord,
    connect_readonly,
    dsn_from_env,
    load_feature_rows,
    load_labels,
    load_span,
    output_span,
    sanitize_error,
)
from app.ml.sources import feature_source_names

logger = logging.getLogger(__name__)

INFO_SOURCE = "pregame"
_REPO_ROOT = Path(__file__).resolve().parents[3]

IDENTITY_COLUMNS = (
    "league",
    "season",
    "date",
    "bdl_game_id",
    "bdl_player_id",
    "bdl_team_id",
    "season_type",
    "is_home",
    "info_source",
    "as_of",
    "tip_fallback",
)

OUTPUT_COLUMNS = IDENTITY_COLUMNS + COUNT_COLUMNS + form_column_names() + label_column_names()

INT_COLUMNS = (
    "season",
    "bdl_game_id",
    "bdl_player_id",
    "bdl_team_id",
    "n_prev_games",
    "n_played_prev",
    "dnp_last_10",
    "dnp_last_10_window",
    "days_rest",
) + label_column_names()
FLOAT_COLUMNS = form_column_names()
NULLABLE_BOOL_COLUMNS = ("is_home", "is_back_to_back")
_OUTPUT_SET = frozenset(OUTPUT_COLUMNS)


class DatasetError(ValueError):
    """The loaded rows cannot be turned into a dataset."""


@dataclass(frozen=True, slots=True)
class Dataset:
    """Output rows and the metadata dict written beside the Parquet."""

    rows: list[dict[str, object]]
    metadata: dict[str, object]


def parse_seasons(text: str) -> tuple[int, int]:
    """Parse ``START:END``. Both years are inclusive.

    Raises:
        argparse.ArgumentTypeError: the text is not two four-digit years,
            or the end is before the start.
    """
    parts = text.strip().split(":")
    if len(parts) != 2 or not all(len(part) == 4 and part.isdigit() for part in parts):
        raise argparse.ArgumentTypeError(
            "seasons must be START:END with four-digit years; both ends are inclusive"
        )
    start, end = int(parts[0]), int(parts[1])
    if end < start:
        raise argparse.ArgumentTypeError("season end is before start; both ends are inclusive")
    return start, end


def _hours(text: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("hours-before-tip must be a number") from exc
    if value < 0 or value != value or value == float("inf"):
        raise argparse.ArgumentTypeError("hours-before-tip must be a finite number >= 0")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Return the CLI parser. ``--hours-before-tip`` defaults to 3."""
    parser = argparse.ArgumentParser(
        prog="python -m app.ml.build_dataset",
        description=(
            "Export one Parquet row per player_game_stats row. "
            "Season endpoints are inclusive."
        ),
    )
    parser.add_argument(
        "--dsn-env",
        required=True,
        help="Environment variable that holds the read-only DSN. The value is never printed.",
    )
    parser.add_argument(
        "--seasons",
        required=True,
        type=parse_seasons,
        help="Inclusive season range START:END, for example 2015:2025.",
    )
    parser.add_argument(
        "--hours-before-tip",
        type=_hours,
        default=DEFAULT_HOURS_BEFORE_TIP,
        help="Hours before tip-off that define T. Default: 3.",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Parquet path. Metadata is written to <file>.meta.json.",
    )
    parser.add_argument("--league", default="nba", choices=("nba", "wnba"))
    return parser


def metadata_path(parquet_path: Path) -> Path:
    """Return ``<file>.meta.json`` for ``--out <file>.parquet``."""
    path = Path(parquet_path)
    if path.suffix == ".parquet":
        return path.with_suffix(".meta.json")
    return path.with_name(path.name + ".meta.json")


def read_git_head() -> str:
    """Return the current commit, or ``unknown`` when git cannot answer."""
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return "unknown"
    sha = output.strip()
    if len(sha) != 40 or any(ch not in "0123456789abcdef" for ch in sha):
        return "unknown"
    return sha


def _json_number(value: float) -> int | float:
    if value == int(value):
        return int(value)
    return value


def _index_games(games: Sequence[GameRecord], league: str) -> dict[tuple[str, int], GameRecord]:
    indexed: dict[tuple[str, int], GameRecord] = {}
    for game in games:
        if game.league != league:
            continue
        key = (game.league, game.bdl_game_id)
        if key in indexed:
            raise DatasetError(f"duplicate game {game.bdl_game_id}")
        indexed[key] = game
    return indexed


def _group_stats(stats: Sequence[StatRecord], league: str) -> dict[tuple[str, int], list[StatRecord]]:
    grouped: dict[tuple[str, int], list[StatRecord]] = {}
    seen: set[tuple[str, int, int]] = set()
    for row in stats:
        if row.league != league:
            continue
        key = (row.league, row.bdl_game_id, row.bdl_player_id)
        if key in seen:
            raise DatasetError(
                f"duplicate player_game_stats row for game {row.bdl_game_id} "
                f"player {row.bdl_player_id}"
            )
        seen.add(key)
        grouped.setdefault((row.league, row.bdl_player_id), []).append(row)
    return grouped


def _index_actuals(
    actuals: Sequence[ActualRecord], league: str
) -> dict[tuple[str, int, int], dict[str, int | None]]:
    indexed: dict[tuple[str, int, int], dict[str, int | None]] = {}
    for actual in actuals:
        if actual.league != league:
            continue
        key = (actual.league, actual.bdl_game_id, actual.bdl_player_id)
        bucket = indexed.setdefault(key, {})
        current = bucket.get(actual.market)
        if actual.market in bucket and current != actual.actual_value:
            raise DatasetError(f"conflicting label for {actual.market}")
        bucket[actual.market] = actual.actual_value
    return indexed


def assemble_dataset(
    games: Sequence[GameRecord],
    stats: Sequence[StatRecord],
    actuals: Sequence[ActualRecord],
    *,
    season_start: int,
    season_end: int,
    hours_before_tip: float = DEFAULT_HOURS_BEFORE_TIP,
    git_head: str,
    league: str = "nba",
) -> Dataset:
    """Build dataset rows from already loaded records.

    Stats from seasons before ``season_start`` are features only. They are
    not dropped when the output window starts. A row whose labels are all
    NULL is removed. ``info_source`` is ``pregame`` on every kept row.

    Args:
        games: Schedule rows, including the season before the output window.
        stats: Player-game rows for that same load window.
        actuals: Label rows for the output seasons.
        season_start: First output season, inclusive.
        season_end: Last output season, inclusive.
        hours_before_tip: Subtracted from tip-off. Defaults to 3.
        git_head: Commit recorded in the metadata.
        league: League to keep. Ids overlap across leagues, so the other
            league is ignored.

    Returns:
        Kept rows and the metadata dict.
    """
    if season_end < season_start:
        raise DatasetError("season end is before season start")
    by_game = _index_games(games, league)
    by_player = _group_stats(stats, league)
    by_label = _index_actuals(actuals, league)

    kept: list[dict[str, object]] = []
    candidates = 0
    fallbacks = 0
    for player_rows in by_player.values():
        for target in player_rows:
            if target.season < season_start or target.season > season_end:
                continue
            candidates += 1
            game = by_game.get((target.league, target.bdl_game_id))
            if game is None:
                raise DatasetError(f"game {target.bdl_game_id} is missing from the loaded games")
            if game.game_date != target.game_date or game.season != target.season:
                raise DatasetError(
                    f"game {target.bdl_game_id} does not match the stat row's date or season"
                )
            instant = prediction_instant(game.game_date, game.datetime_utc, hours_before_tip)
            row = features_for_target(player_rows, target, game)
            row["info_source"] = INFO_SOURCE
            row["as_of"] = instant.as_of
            row["tip_fallback"] = instant.tip_fallback
            labels = pivot_labels(by_label.get((target.league, target.bdl_game_id, target.bdl_player_id), {}))
            if labels is None:
                continue
            row.update(labels)
            extra = [name for name in row if name not in _OUTPUT_SET]
            missing = [name for name in OUTPUT_COLUMNS if name not in row]
            if extra or missing:
                raise DatasetError(f"row columns missing={missing} extra={extra}")
            kept.append(row)
            if instant.tip_fallback:
                fallbacks += 1

    kept.sort(key=lambda item: (item["date"], item["bdl_game_id"], item["bdl_player_id"]))
    null_counts = {column: 0 for column in label_column_names()}
    for row in kept:
        for column in null_counts:
            if row[column] is None:
                null_counts[column] += 1
    metadata: dict[str, object] = {
        "seasons": {"start": season_start, "end": season_end, "inclusive": True},
        "history_season_start": season_start - 1,
        "hours_before_tip": _json_number(hours_before_tip),
        "t_rule": T_RULE,
        "null_tip_fallback_count": fallbacks,
        "git_head": git_head,
        "row_count": len(kept),
        "rows_before_label_filter": candidates,
        "label_drop_count": candidates - len(kept),
        "label_null_counts": null_counts,
        "info_source": INFO_SOURCE,
        "league": league,
        "feature_sources": list(feature_source_names()),
        "label_source": "prop_actuals",
    }
    return Dataset(rows=kept, metadata=metadata)


def frame_from_rows(rows: Sequence[Mapping[str, object]]) -> object:
    """Build a DataFrame with nullable integers and floats.

    The return type is the pandas DataFrame. Pandas is imported here so
    importing the assembler does not import it, and the API process never
    reaches this function.
    """
    import pandas as pd

    frame = pd.DataFrame(list(rows), columns=list(OUTPUT_COLUMNS))
    for name in INT_COLUMNS:
        frame[name] = pd.to_numeric(frame[name], errors="coerce").astype("Int64")
    for name in FLOAT_COLUMNS:
        frame[name] = pd.to_numeric(frame[name], errors="coerce").astype("Float64")
    for name in NULLABLE_BOOL_COLUMNS:
        frame[name] = frame[name].astype("boolean")
    frame["tip_fallback"] = frame["tip_fallback"].astype("boolean")
    frame["as_of"] = pd.to_datetime(frame["as_of"], utc=True)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    return frame


def write_outputs(dataset: Dataset, out: Path) -> Path:
    """Write the Parquet file and ``<file>.meta.json``. Return the meta path."""
    import pandas as pd

    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = frame_from_rows(dataset.rows)
    if not isinstance(frame, pd.DataFrame):
        raise DatasetError("internal frame was not a DataFrame")
    frame.to_parquet(path, index=False, engine="pyarrow")
    meta_path = metadata_path(path)
    meta_path.write_text(
        json.dumps(dataset.metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return meta_path


async def export_dataset(
    *,
    dsn_env: str,
    season_start: int,
    season_end: int,
    hours_before_tip: float,
    out: Path,
    league: str = "nba",
    git_head: str | None = None,
) -> dict[str, object]:
    """Load one window and write Parquet plus metadata.

    The connection is read-only and is closed before the files are written.
    """
    dsn = dsn_from_env(dsn_env)
    conn = await connect_readonly(dsn)
    try:
        games, stats = await load_feature_rows(
            conn, league=league, seasons=load_span(season_start, season_end)
        )
        actuals = await load_labels(
            conn, league=league, seasons=output_span(season_start, season_end)
        )
    finally:
        await conn.close()
    dataset = assemble_dataset(
        games,
        stats,
        actuals,
        season_start=season_start,
        season_end=season_end,
        hours_before_tip=hours_before_tip,
        git_head=git_head if git_head is not None else read_git_head(),
        league=league,
    )
    write_outputs(dataset, out)
    logger.info("wrote %s rows", dataset.metadata["row_count"])
    return dataset.metadata


def main(argv: list[str] | None = None) -> int:
    """CLI entry. Returns 0 on success and 1 on a data or connection error."""
    args = build_parser().parse_args(argv)
    start, end = args.seasons
    try:
        meta = asyncio.run(
            export_dataset(
                dsn_env=args.dsn_env,
                season_start=start,
                season_end=end,
                hours_before_tip=args.hours_before_tip,
                out=args.out,
                league=args.league,
            )
        )
    except (LoadError, DatasetError, OSError, ValueError) as exc:
        print(sanitize_error(exc), file=sys.stderr)
        return 1
    print(f"wrote {meta['row_count']} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
