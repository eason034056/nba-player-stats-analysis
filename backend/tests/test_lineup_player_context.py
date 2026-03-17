import os
import sys

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import lineup_source_support as source_support
from scripts.agents.tools import historical


@pytest.mark.asyncio
async def test_get_player_lineup_context_canonicalizes_player_name_before_matching(monkeypatch):
    async def fake_get_projected_lineup_consensus(team: str, date: str = ""):
        return {
            "signal": "neutral",
            "effect_size": 0.0,
            "sample_size": 5,
            "reliability": 0.85,
            "window": "today",
            "source": "lineup_consensus",
            "as_of": "2026-03-16T18:00:00+00:00",
            "details": {
                "team": team,
                "status": "projected",
                "confidence": "high",
                "source_disagreement": False,
                "freshness_minutes": 5,
                "starters": ["OG Anunoby", "Jalen Brunson", "Mikal Bridges", "Josh Hart", "Karl-Anthony Towns"],
            },
        }

    monkeypatch.setattr(historical, "get_projected_lineup_consensus", fake_get_projected_lineup_consensus)
    monkeypatch.setattr(
        source_support,
        "_get_team_roster_candidates",
        lambda team_code: ["OG Anunoby"] if team_code == "NYK" else [],
    )

    result = await historical.get_player_lineup_context(
        "O.G. Anunoby",
        team="NYK",
    )

    assert result["details"]["player_is_projected_starter"] is True
