#!/usr/bin/env python3
"""Rewrite the committed game-log CSVs from the recorded ESPN schedule.

Usage (from the repo root)::

    python scripts/hygiene_game_logs.py

The upstream RealGM scraper (``scrape_nba.py``) sets ``SEASON = "2025-2026"``
and writes that string on every row, including games from other seasons.
It also selects "All Games", so Summer League and preseason share the
file with the regular season. This command is what a re-download must
run — ``CSVDownloaderService`` calls the same function — so pulling the
raw CSV again does not put the bad labels back.

Season boundaries come from ``tests/fixtures/espn/schedule_events.json``,
which ``scripts/explore_espn_schedule_api.py`` records from ESPN. This
script does not call the network.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The hygiene module lives in the backend package.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "backend"))

from app.services.game_log_hygiene import hygiene_csv_file  # noqa: E402


def main() -> None:
    """Rewrite both league files and print the before/after counts."""
    targets = [
        (_ROOT / "data" / "nba_player_game_logs.csv", "nba"),
        (_ROOT / "data" / "wnba_player_game_logs.csv", "wnba"),
    ]
    for path, league in targets:
        if not path.exists():
            print(f"missing {path}")
            continue
        report = hygiene_csv_file(path, league=league)
        if report is None:
            print(f"skipped {path}")
            continue
        print(
            f"{path.name} [{league}] {report.input_rows} -> {report.output_rows} "
            f"kept={report.kept} seasons={report.seasons_kept} "
            f"dropped={report.dropped} dupes={report.duplicates_removed}"
        )


if __name__ == "__main__":
    main()
