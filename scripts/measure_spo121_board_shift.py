#!/usr/bin/env python3
"""Print the SPO-121 board shift for one recorded player_points capture.

Run from the repository root:

    python scripts/measure_spo121_board_shift.py

The script loads tests/fixtures/odds_api_event_odds__player_points.json
and data/nba_player_game_logs.csv through the production analysis path.
Projections are omitted, so the projection and defense adjustments are
zero. It does not call the Odds API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from tests.test_spo121_bulk_reads import recorded_points_shift  # noqa: E402


def main() -> None:
    """Print the shift counts and the row labels as JSON."""
    shift = recorded_points_shift()
    print(json.dumps(shift, indent=2))


if __name__ == "__main__":
    main()
