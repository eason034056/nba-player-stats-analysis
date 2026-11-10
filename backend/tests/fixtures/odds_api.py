"""Load recorded The Odds API bodies.

The JSON files in this directory are byte-for-byte responses. Tests must
call ``load_odds_fixture`` instead of typing an event or odds payload.
"""

import json
from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent


def load_odds_fixture(name: str) -> Any:
    """Return the parsed JSON for one recorded Odds API fixture.

    Args:
        name: File name inside ``backend/tests/fixtures``, for example
            ``odds_api_events__basketball_nba.json``. A path with a
            directory segment is rejected so a test cannot read an
            arbitrary file through this helper.

    Returns:
        The parsed JSON value. Events fixtures are a list. Odds fixtures
        are one event object.

    Raises:
        ValueError: ``name`` is not a bare file name.
        FileNotFoundError: That fixture was not recorded.
    """
    if Path(name).name != name or not name.endswith(".json"):
        raise ValueError(f"fixture name must be a recorded json file, got {name!r}")
    path = _DIR / name
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text())
