import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "scripts", "agents")
    ),
)

import agents as agent_module


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


class _FakeLLM:
    def __init__(self, content: str):
        self._content = content

    async def ainvoke(self, _messages):
        return _FakeResponse(self._content)


@pytest.mark.asyncio
async def test_planner_node_overrides_llm_parse_with_selected_pick_context(monkeypatch):
    monkeypatch.setattr(
        agent_module,
        "_get_llm",
        lambda: _FakeLLM(
            """
            {
              "player": "Wrong Player",
              "metric": "assists",
              "threshold": 7.5,
              "date": "2026-03-20",
              "opponent": "Wrong Team",
              "direction": "under",
              "needs_market": true,
              "needs_historical": true,
              "needs_projection": false,
              "comparison_players": []
            }
            """
        ),
    )

    result = await agent_module.planner_node(
        {
            "user_query": "Should I bet this?",
            "event_context": {
                "action": "analyze_pick",
                "date": "2026-03-13",
                "selected_pick": {
                    "event_id": "evt-1",
                    "player_name": "Stephen Curry",
                    "player_team": "Golden State Warriors",
                    "metric": "points",
                    "threshold": 28.5,
                    "direction": "over",
                    "home_team": "Los Angeles Lakers",
                    "away_team": "Golden State Warriors",
                },
            },
            "audit_log": [],
        }
    )

    parsed = result["parsed_query"]
    assert parsed["player"] == "Stephen Curry"
    assert parsed["metric"] == "points"
    assert parsed["threshold"] == 28.5
    assert parsed["date"] == "2026-03-13"
    assert parsed["direction"] == "over"
    assert parsed["event_id"] == "evt-1"
    assert parsed["home_team"] == "Los Angeles Lakers"
    assert parsed["away_team"] == "Golden State Warriors"
    assert parsed["opponent"] == "Los Angeles Lakers"
