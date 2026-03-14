import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.models.agent_chat import AgentChatRequest
from app.services.agent_chat import AgentChatService, _resolve_agents_dir


def _make_pick(**overrides):
    pick = {
        "player_name": "Stephen Curry",
        "player_team": "Golden State Warriors",
        "event_id": "evt-1",
        "home_team": "Los Angeles Lakers",
        "away_team": "Golden State Warriors",
        "commence_time": "2026-03-13T02:00:00Z",
        "metric": "points",
        "threshold": 28.5,
        "direction": "over",
        "probability": 0.72,
        "n_games": 20,
    }
    pick.update(overrides)
    return pick


def _make_graph_result(
    *,
    decision: str = "over",
    confidence: float = 0.81,
    model_probability: float = 0.69,
    market_implied_probability: float | None = 0.57,
    expected_value_pct: float = 0.21,
    summary: str = "Model edge is supported by historical hit rate and favorable pricing.",
    data_quality_flags: list[str] | None = None,
    dimensions: dict | None = None,
    risk_factors: list[str] | None = None,
):
    return {
        "final_decision": {
            "decision": decision,
            "confidence": confidence,
            "model_probability": model_probability,
            "market_implied_probability": market_implied_probability,
            "expected_value_pct": expected_value_pct,
            "dimensions": dimensions
            or {
                "historical": {
                    "signal": "positive",
                    "reliability": 0.84,
                    "detail": "Hit rate has stayed above the required threshold.",
                },
                "market": {
                    "signal": "positive",
                    "reliability": 0.71,
                    "detail": "Best available price still shows a clean edge.",
                },
            },
            "risk_factors": risk_factors or ["Opponent pace could suppress volume."],
            "summary": summary,
            "needs_retry": False,
            "retry_reason": None,
        },
        "scorecard": {
            "decision": decision,
            "confidence": confidence,
            "model_probability": model_probability,
            "market_implied_probability": market_implied_probability,
            "expected_value_pct": expected_value_pct,
            "eligible_for_bet": decision != "avoid",
            "data_quality_flags": data_quality_flags or [],
        },
        "critic_notes": risk_factors or ["Opponent pace could suppress volume."],
    }


def test_agent_chat_service_maps_single_pick_analysis():
    captured_queries: list[str] = []

    def graph_runner(query: str):
        captured_queries.append(query)
        return _make_graph_result()

    service = AgentChatService(graph_runner=graph_runner)
    request = AgentChatRequest.model_validate(
        {
            "thread": "thread-1",
            "message": "Should I bet this?",
            "action": "analyze_pick",
            "context": {
                "page": {
                    "route": "/picks",
                    "date": "2026-03-13",
                    "selected_teams": ["Golden State Warriors"],
                },
                "selected_pick": _make_pick(),
            },
        }
    )

    response = service.handle_chat(request)

    assert response.status == "ok"
    assert response.verdict is not None
    assert response.verdict.subject == "Stephen Curry points over 28.5"
    assert response.verdict.decision == "over"
    assert len(response.verdict.reasons) == 2
    assert "Stephen Curry" in captured_queries[0]
    assert "over 28.5 points" in captured_queries[0]


def test_agent_chat_service_surfaces_missing_market_data():
    service = AgentChatService(
        graph_runner=lambda _query: _make_graph_result(
            market_implied_probability=None,
            expected_value_pct=0.0,
            summary="There is not enough current market data to price this bet cleanly.",
            data_quality_flags=["no_market_data"],
        )
    )

    request = AgentChatRequest.model_validate(
        {
            "thread": "thread-2",
            "message": "Summarize line movement",
            "action": "line_movement",
            "context": {
                "page": {"route": "/picks", "date": "2026-03-13"},
                "selected_pick": _make_pick(),
            },
        }
    )

    response = service.handle_chat(request)

    assert response.status == "not_enough_market_data"
    assert "market data" in response.reply.lower()
    assert response.verdict is not None


def test_agent_chat_service_reviews_entire_bet_slip():
    captured_queries: list[str] = []

    def graph_runner(query: str):
        captured_queries.append(query)
        if "Stephen Curry" in query:
            return _make_graph_result(decision="over")
        return _make_graph_result(
            decision="under",
            summary="The current direction is working against the modeled edge.",
        )

    service = AgentChatService(graph_runner=graph_runner)
    request = AgentChatRequest.model_validate(
        {
            "thread": "thread-3",
            "message": "Compare with my slip",
            "action": "review_slip",
            "context": {
                "page": {"route": "/betslip"},
                "bet_slip": [
                    _make_pick(),
                    _make_pick(
                        player_name="LeBron James",
                        player_team="Los Angeles Lakers",
                        direction="over",
                    ),
                ],
            },
        }
    )

    response = service.handle_chat(request)

    assert response.status == "ok"
    assert response.slip_review is not None
    assert response.slip_review.keep_count == 1
    assert response.slip_review.remove_count == 1
    assert response.slip_review.items[0].recommendation == "keep"
    assert response.slip_review.items[1].recommendation == "remove"
    assert len(captured_queries) == 2


def test_agent_chat_endpoint_validates_action_and_uses_service(monkeypatch):
    from app.api import agent as agent_api

    client = TestClient(app)

    invalid_response = client.post(
        "/api/nba/agent/chat",
        json={"thread": "thread-4", "message": "hi", "action": "unknown"},
    )
    assert invalid_response.status_code == 422

    def fake_handle_chat(request: AgentChatRequest):
        return AgentChatService(
            graph_runner=lambda _query: _make_graph_result()
        ).handle_chat(request)

    monkeypatch.setattr(agent_api.agent_chat_service, "handle_chat", fake_handle_chat)

    response = client.post(
        "/api/nba/agent/chat",
        json={
            "thread": "thread-5",
            "message": "Should I bet this?",
            "action": "analyze_pick",
            "context": {
                "page": {"route": "/picks"},
                "selected_pick": _make_pick(),
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["verdict"]["decision"] == "over"


def test_resolve_agents_dir_supports_repo_and_container_layouts(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_service_file = repo_root / "backend" / "app" / "services" / "agent_chat.py"
    repo_service_file.parent.mkdir(parents=True)
    repo_service_file.touch()
    (repo_root / "scripts" / "agents").mkdir(parents=True)

    container_root = tmp_path / "container" / "app"
    container_service_file = (
        container_root / "app" / "services" / "agent_chat.py"
    )
    container_service_file.parent.mkdir(parents=True)
    container_service_file.touch()
    (container_root / "scripts" / "agents").mkdir(parents=True)

    assert _resolve_agents_dir(repo_service_file) == repo_root / "scripts" / "agents"
    assert _resolve_agents_dir(container_service_file) == container_root / "scripts" / "agents"
