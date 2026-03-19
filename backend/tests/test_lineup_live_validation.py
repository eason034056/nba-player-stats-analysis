import os
import re
import sys

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.lineup_provider_rotogrinders import fetch_rotogrinders_lineups
from app.services.lineup_provider_rotowire import fetch_rotowire_lineups


RUN_LIVE = os.environ.get("RUN_LIVE_LINEUP_VALIDATION") == "1"


def _is_dirty_name(name: str) -> bool:
    lowered = name.lower()
    if any(token in lowered for token in (" prob", " ques", " doubt", " gtd", " out")):
        return True
    if "$" in name:
        return True
    if re.search(r"\b\d+(\.\d+)?%?\b", name):
        return True
    return False


@pytest.mark.skipif(not RUN_LIVE, reason="set RUN_LIVE_LINEUP_VALIDATION=1 to hit live lineup sites")
def test_live_rotowire_and_rotogrinders_sources_return_clean_lineups():
    target_date = "2026-03-16"

    rotowire = fetch_rotowire_lineups(target_date)
    rotogrinders = fetch_rotogrinders_lineups(target_date)

    assert len(rotowire) >= 2
    assert len(rotogrinders) >= 2

    shared_teams = sorted(set(rotowire) & set(rotogrinders))
    assert len(shared_teams) >= 2

    checked = 0
    for team in shared_teams:
        rw_lineup = rotowire[team]
        rg_lineup = rotogrinders[team]
        if len(rw_lineup.get("starters") or []) < 5 or len(rg_lineup.get("starters") or []) < 5:
            continue

        for starter in rw_lineup["starters"][:5] + rg_lineup["starters"][:5]:
            assert not _is_dirty_name(starter), f"dirty starter name remained for {team}: {starter}"

        checked += 1
        if checked >= 3:
            break

    assert checked >= 3
