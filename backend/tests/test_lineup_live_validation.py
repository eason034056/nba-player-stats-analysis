"""One live projected-lineups call. Skipped unless a key is configured."""

from __future__ import annotations

import os

import pytest

from app.services.bdl_client import BdlClient
from app.services.slate_date import nba_slate_date


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1" or not os.environ.get("BALLDONTLIE_API_KEY"),
    reason="Set RUN_INTEGRATION=1 and BALLDONTLIE_API_KEY to call BALLDONTLIE.",
)
async def test_live_projected_lineups_for_the_current_slate():
    """One ``list_games`` plus one ``list_projected_lineups`` for today's slate.

    The key stays in the client header. This test does not print it.
    """
    slate = nba_slate_date()[0]
    client = BdlClient()
    try:
        games = await client.list_games(dates=[slate], per_page=100)
        data = games.get("data")
        assert isinstance(data, list)
        game_ids = [game["id"] for game in data if isinstance(game, dict) and isinstance(game.get("id"), int)]
        if not game_ids:
            pytest.skip("no games on the current slate")
        body = await client.list_projected_lineups(game_ids=game_ids[:12])
    finally:
        await client.aclose()
    assert isinstance(body.get("data"), list)
    assert isinstance(body.get("meta"), dict)
