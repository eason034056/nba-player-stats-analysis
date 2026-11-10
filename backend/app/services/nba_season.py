"""Current NBA season label from the recorded ESPN season documents.

The windows are ``tests/fixtures/espn/seasons/nba_*.json``. Each file is
a core-API season document (``startDate``, ``endDate``, ``displayName``).
Nothing here treats October as a boundary. The label uses the same
expansion as :func:`season_label_for_event`: ``2026-27`` becomes
``2026-2027``, which is the form on the game-log ``Season`` column.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from app.services.game_log_hygiene import season_label_for_event


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _season_dir() -> Path:
    return _repo_root() / "tests" / "fixtures" / "espn" / "seasons"


@lru_cache(maxsize=1)
def _nba_season_windows() -> tuple[tuple[str, str, str], ...]:
    """``(start_day, end_day, csv_label)`` from each recorded NBA season file."""
    windows: list[tuple[str, str, str]] = []
    folder = _season_dir()
    for path in sorted(folder.glob("nba_*.json")):
        if path.name == "nba_index.json":
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        start = str(document.get("startDate") or "")[:10]
        end = str(document.get("endDate") or "")[:10]
        if len(start) < 10 or len(end) < 10:
            continue
        label = season_label_for_event(
            {
                "league": "nba",
                "season": {
                    "displayName": document.get("displayName"),
                    "year": document.get("year"),
                },
            }
        )
        if not label:
            continue
        windows.append((start, end, label))
    return tuple(windows)


def normalize_nba_season_label(value: str | None) -> str:
    """CSV season label for a query value.

    ``2025-26`` and ``2025-2026`` both become ``2025-2026``. A blank
    value stays blank. A single calendar year is returned unchanged,
    which is the WNBA shape and is not rewritten into an NBA span.
    """
    text = (value or "").strip()
    if not text:
        return ""
    return season_label_for_event(
        {"league": "nba", "season": {"displayName": text}}
    )


def recorded_nba_season_label(moment: datetime | None = None) -> str:
    """CSV label of the recorded NBA season that contains ``moment``.

    Inclusive on ``startDate`` and ``endDate`` (the date prefix). When
    ``moment`` sits in a gap, the season that started most recently
    before it is used. When every recorded season starts later, the
    earliest window is used so the caller still gets a label.
    """
    if moment is None:
        moment = datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    day = moment.astimezone(timezone.utc).date().isoformat()
    windows = _nba_season_windows()
    if not windows:
        return ""
    covering = [item for item in windows if item[0] <= day <= item[1]]
    if covering:
        covering.sort()
        return covering[-1][2]
    started = [item for item in windows if item[0] <= day]
    if started:
        started.sort()
        return started[-1][2]
    return sorted(windows)[0][2]
