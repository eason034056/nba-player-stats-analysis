"""Load recorded external API bodies from ``backend/tests/fixtures``.

Unit tests call ``load_odds_fixture`` instead of typing an Odds API body.
The bytes on disk are the capture. This module only parses them.
"""

from __future__ import annotations

import json
from pathlib import Path

_FIXTURE_DIR = Path(__file__).resolve().parent


def load_odds_fixture(name: str) -> dict:
    """Parse one JSON fixture that sits next to this module.

    Args:
        name: File name only, for example
            ``odds_api_event_odds__player_points.json``. A path separator
            is rejected so a test cannot read outside the fixture directory.

    Returns:
        The parsed JSON object. A new object is returned on every call,
        so a test can edit its copy without changing the file or the
        next call.

    Raises:
        ValueError: ``name`` is not a bare ``.json`` file name.
        FileNotFoundError: That file is not in the fixture directory.
    """
    if not name.endswith(".json") or "/" in name or "\\" in name or name in {".", ".."}:
        raise ValueError(f"fixture name must be a single json file, got {name!r}")
    path = _FIXTURE_DIR / name
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))
