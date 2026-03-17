import os
import sys
from pathlib import Path

import pytest
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


def _make_query_aligned_context(
    *,
    query_side: str = "over",
    threshold: float = 28.5,
    historical_query_probability: float = 0.69,
    historical_p_over: float | None = None,
    historical_p_under: float | None = None,
    historical_mean: float = 30.12,
    historical_supports_query_side: bool = True,
    recent_average: float = 31.4,
    season_average: float = 29.7,
    recent_minus_threshold: float = 2.9,
    trend_supports_query_side: bool = True,
    signal_alignment: str = "supports_query_side",
    pricing_mode: str = "exact_line",
    market_query_probability: float | None = 0.57,
    queried_line: float = 28.5,
    best_line: float | None = 28.5,
    available_lines: list[float] | None = None,
    best_book: str | None = "draftkings",
    best_odds: int | None = -110,
    is_back_to_back: bool = False,
    unresolved: bool = False,
    questionable_players: list[str] | None = None,
    out_players: list[str] | None = None,
):
    if historical_p_over is None:
        historical_p_over = historical_query_probability if query_side == "over" else 1.0 - historical_query_probability
    if historical_p_under is None:
        historical_p_under = historical_query_probability if query_side == "under" else 1.0 - historical_query_probability

    return {
        "query_side": query_side,
        "historical": {
            "p_over": historical_p_over,
            "p_under": historical_p_under,
            "query_probability": historical_query_probability,
            "mean": historical_mean,
            "threshold": threshold,
            "mean_minus_threshold": historical_mean - threshold,
            "supports_query_side": historical_supports_query_side,
        },
        "trend": {
            "window": "last_5",
            "recent_average": recent_average,
            "season_average": season_average,
            "recent_minus_threshold": recent_minus_threshold,
            "supports_query_side": trend_supports_query_side,
            "signal_alignment": signal_alignment,
        },
        "market": {
            "pricing_mode": pricing_mode,
            "query_probability": market_query_probability,
            "queried_line": queried_line,
            "best_line": best_line,
            "available_lines": available_lines or ([queried_line] if pricing_mode == "exact_line" else []),
            "best_book": best_book,
            "best_odds": best_odds,
        },
        "schedule": {
            "is_back_to_back": is_back_to_back,
        },
        "injuries": {
            "unresolved": unresolved,
            "questionable_players": questionable_players or [],
            "out_players": out_players or [],
        },
    }


def _make_signal(
    *,
    signal: str = "neutral",
    reliability: float = 0.5,
    sample_size: int = 0,
    details: dict | None = None,
):
    return {
        "signal": signal,
        "reliability": reliability,
        "sample_size": sample_size,
        "details": details or {},
    }


def _make_graph_result(
    *,
    decision: str = "over",
    confidence: float = 0.81,
    model_probability: float = 0.69,
    market_implied_probability: float | None = 0.57,
    expected_value_pct: float | None = 0.21,
    summary: str = "Model edge is supported by historical hit rate and favorable pricing.",
    data_quality_flags: list[str] | None = None,
    dimensions: dict | None = None,
    risk_factors: list[str] | None = None,
    market_pricing_mode: str = "exact_line",
    queried_line: float = 28.5,
    best_line: float | None = 28.5,
    available_lines: list[float] | None = None,
    best_book: str | None = "draftkings",
    best_odds: int | None = -110,
    eligible_for_bet: bool | None = None,
    query_aligned_context: dict | None = None,
    lineup_context: dict | None = None,
    historical_signals: dict | None = None,
    market_signals: dict | None = None,
    projection_signals: dict | None = None,
):
    if eligible_for_bet is None:
        eligible_for_bet = decision != "avoid" and market_pricing_mode == "exact_line"
    return {
        "final_decision": {
            "decision": decision,
            "confidence": confidence,
            "model_probability": model_probability,
            "market_implied_probability": market_implied_probability,
            "expected_value_pct": expected_value_pct,
            "market_pricing_mode": market_pricing_mode,
            "queried_line": queried_line,
            "best_line": best_line,
            "available_lines": available_lines or ([queried_line] if market_pricing_mode == "exact_line" else []),
            "best_book": best_book,
            "best_odds": best_odds,
            "query_aligned_context": query_aligned_context,
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
            "lineup_context": lineup_context,
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
            "market_pricing_mode": market_pricing_mode,
            "queried_line": queried_line,
            "best_line": best_line,
            "available_lines": available_lines or ([queried_line] if market_pricing_mode == "exact_line" else []),
            "best_book": best_book,
            "best_odds": best_odds,
            "eligible_for_bet": eligible_for_bet,
            "data_quality_flags": data_quality_flags or [],
            "query_aligned_context": query_aligned_context,
            "lineup_context": lineup_context,
        },
        "critic_notes": risk_factors or ["Opponent pace could suppress volume."],
        "historical_signals": historical_signals or {},
        "market_signals": market_signals or {},
        "projection_signals": projection_signals or {},
    }


@pytest.mark.asyncio
async def test_agent_chat_service_maps_single_pick_analysis():
    captured_calls: list[tuple[str, dict[str, object]]] = []

    async def graph_runner(query: str, event_context: dict[str, object]):
        captured_calls.append((query, event_context))
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

    response = await service.handle_chat(request)

    assert response.status == "ok"
    assert response.verdict is not None
    assert response.verdict.subject == "Stephen Curry points over 28.5"
    assert response.verdict.decision == "over"
    assert len(response.verdict.reasons) == 2
    query, event_context = captured_calls[0]
    assert "Stephen Curry" in query
    assert "over 28.5 points" in query
    assert event_context["event_id"] == "evt-1"
    assert event_context["player_name"] == "Stephen Curry"
    assert event_context["metric"] == "points"
    assert event_context["threshold"] == 28.5
    assert event_context["direction"] == "over"
    assert event_context["date"] == "2026-03-13"
    assert event_context["home_team"] == "Los Angeles Lakers"
    assert event_context["away_team"] == "Golden State Warriors"


@pytest.mark.asyncio
async def test_agent_chat_service_surfaces_missing_market_data():
    async def graph_runner(_query: str, _event_context: dict[str, object]):
        return _make_graph_result(
            market_implied_probability=None,
            expected_value_pct=None,
            summary="There is not enough current market data to price this bet cleanly.",
            data_quality_flags=["no_market_data"],
            market_pricing_mode="unavailable",
            best_line=None,
            available_lines=[],
            best_book=None,
            best_odds=None,
            eligible_for_bet=False,
        )

    service = AgentChatService(
        graph_runner=graph_runner
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

    response = await service.handle_chat(request)

    assert response.status == "not_enough_market_data"
    assert "market data" in response.reply.lower()
    assert response.verdict is not None
    assert response.verdict.market_pricing_mode == "unavailable"


@pytest.mark.asyncio
async def test_agent_chat_service_maps_lineup_context():
    async def graph_runner(_query: str, _event_context: dict[str, object]):
        return _make_graph_result(
            summary="Lineup support is stable and role looks secure.",
            lineup_context={
                "summary": "Projected starters are aligned across both sources.",
                "freshness_risk": False,
                "player_team": {
                    "team": "GSW",
                    "status": "projected",
                    "confidence": "high",
                    "source_disagreement": False,
                    "updated_at": "2026-03-13T00:20:00Z",
                    "player_is_projected_starter": True,
                    "starters": [
                        "Stephen Curry",
                        "Brandin Podziemski",
                        "Andrew Wiggins",
                        "Draymond Green",
                        "Trayce Jackson-Davis",
                    ],
                },
                "opponent_team": {
                    "team": "LAL",
                    "status": "partial",
                    "confidence": "low",
                    "source_disagreement": True,
                    "updated_at": "2026-03-13T00:15:00Z",
                    "player_is_projected_starter": None,
                    "starters": ["Austin Reaves", "LeBron James"],
                },
            },
        )

    service = AgentChatService(graph_runner=graph_runner)
    request = AgentChatRequest.model_validate(
        {
            "thread": "thread-lineups",
            "message": "Should I bet this?",
            "action": "analyze_pick",
            "context": {
                "page": {"route": "/picks", "date": "2026-03-13"},
                "selected_pick": _make_pick(),
            },
        }
    )

    response = await service.handle_chat(request)

    assert response.verdict is not None
    assert response.verdict.lineup_context is not None
    assert response.verdict.lineup_context.player_team is not None
    assert response.verdict.lineup_context.player_team.player_is_projected_starter is True
    assert response.verdict.lineup_context.opponent_team is not None
    assert response.verdict.lineup_context.opponent_team.source_disagreement is True


@pytest.mark.asyncio
async def test_agent_chat_service_builds_structured_breakdown_sections_in_order():
    query_aligned_context = _make_query_aligned_context(
        query_side="under",
        threshold=4.5,
        historical_query_probability=0.8864,
        historical_p_over=0.1136,
        historical_p_under=0.8864,
        historical_mean=2.98,
        historical_supports_query_side=True,
        recent_average=5.33,
        season_average=2.98,
        recent_minus_threshold=0.83,
        trend_supports_query_side=False,
        signal_alignment="against_query_side",
        pricing_mode="exact_line",
        market_query_probability=0.5323,
        queried_line=4.5,
        best_line=4.5,
        available_lines=[4.5],
        best_book="draftkings",
        best_odds=-110,
        questionable_players=["Tyrese Maxey"],
    )

    historical_signals = {
        "get_base_stats": _make_signal(
            signal="under",
            reliability=0.84,
            sample_size=42,
            details={"mean": 2.98},
        ),
        "get_role_conditioned_base_stats": _make_signal(
            signal="under",
            reliability=0.68,
            sample_size=6,
            details={"mean": 2.52, "role": "bench"},
        ),
        "get_trend_analysis": _make_signal(
            signal="over",
            reliability=0.73,
            sample_size=42,
        ),
        "get_shooting_profile": _make_signal(
            signal="neutral",
            reliability=0.61,
            sample_size=42,
            details={
                "season": {"fg_pct": 0.451},
                "last_5": {"fg_pct": 0.438},
                "fg_diff": -0.013,
                "flags": [],
            },
        ),
        "get_variance_profile": _make_signal(
            signal="caution",
            reliability=0.77,
            sample_size=42,
            details={"cv": 0.46, "p10": 1.0, "p90": 8.0},
        ),
        "get_schedule_context": _make_signal(
            signal="neutral",
            reliability=0.55,
            sample_size=42,
            details={
                "days_rest": 2,
                "is_back_to_back": False,
                "avg_minutes_by_rest": {"normal": 31.2},
            },
        ),
        "auto_teammate_impact": _make_signal(
            signal="caution",
            reliability=0.66,
            sample_size=42,
            details={
                "teammate_chemistry": [
                    {
                        "star": "Tyrese Maxey",
                        "injury_status": "Questionable",
                        "chemistry_delta": 1.6,
                    }
                ]
            },
        ),
        "get_own_team_injury_report": _make_signal(
            signal="caution",
            reliability=0.9,
            sample_size=1,
            details={
                "injuries": [{"player": "Tyrese Maxey", "status": "Questionable"}]
            },
        ),
        "get_player_lineup_context": _make_signal(
            signal="positive",
            reliability=0.82,
            sample_size=5,
            details={
                "player_is_projected_starter": True,
                "source_disagreement": False,
                "freshness_risk": False,
                "confidence": "high",
                "status": "projected",
            },
        ),
        "get_own_team_projected_lineup": _make_signal(
            signal="neutral",
            reliability=0.82,
            sample_size=5,
            details={"confidence": "high", "status": "projected"},
        ),
        "get_opponent_projected_lineup": _make_signal(
            signal="neutral",
            reliability=0.7,
            sample_size=5,
            details={"confidence": "medium", "status": "projected"},
        ),
    }
    market_signals = {
        "get_current_market": _make_signal(
            signal="neutral",
            reliability=0.74,
            sample_size=5,
            details={"n_books": 5},
        ),
        "get_market_quote_for_line": _make_signal(
            signal="neutral",
            reliability=0.74,
            sample_size=5,
            details={"pricing_mode": "exact_line"},
        ),
        "get_bookmaker_spread": _make_signal(
            signal="neutral",
            reliability=0.7,
            sample_size=5,
            details={"line_spread": 0.5},
        ),
    }

    async def graph_runner(_query: str, _event_context: dict[str, object]):
        return _make_graph_result(
            decision="under",
            confidence=0.9,
            model_probability=0.8864,
            market_implied_probability=0.5323,
            expected_value_pct=0.6652,
            summary="Structured breakdown is ready.",
            query_aligned_context=query_aligned_context,
            lineup_context={
                "summary": "Projected starters are aligned across both sources and the player's role looks stable.",
                "freshness_risk": False,
                "player_team": {
                    "team": "PHI",
                    "status": "projected",
                    "confidence": "high",
                    "source_disagreement": False,
                    "updated_at": "2026-03-13T00:20:00Z",
                    "player_is_projected_starter": True,
                    "starters": ["Test Player"],
                },
                "opponent_team": {
                    "team": "MIA",
                    "status": "projected",
                    "confidence": "medium",
                    "source_disagreement": False,
                    "updated_at": "2026-03-13T00:15:00Z",
                    "player_is_projected_starter": None,
                    "starters": ["Opponent Player"],
                },
            },
            historical_signals=historical_signals,
            market_signals=market_signals,
        )

    service = AgentChatService(graph_runner=graph_runner)
    request = AgentChatRequest.model_validate(
        {
            "thread": "thread-breakdown-sections",
            "message": "Should I bet this?",
            "action": "analyze_pick",
            "context": {
                "page": {"route": "/picks", "date": "2026-03-13"},
                "selected_pick": _make_pick(
                    player_name="Test Player",
                    player_team="PHI",
                    home_team="MIA",
                    away_team="PHI",
                    metric="rebounds",
                    direction="under",
                    threshold=4.5,
                ),
            },
        }
    )

    response = await service.handle_chat(request)

    assert response.verdict is not None
    assert response.verdict.breakdown is not None
    assert [section.key for section in response.verdict.breakdown.sections] == [
        "historical",
        "trend_role",
        "shooting",
        "variance",
        "schedule",
        "own_team_injuries",
        "lineup",
        "market",
        "projection",
    ]
    assert response.verdict.breakdown.sections[0].signal_note == (
        "Historical data gives 88.6% to go under, with a mean of 2.98 versus a 4.50 line."
    )
    assert response.verdict.breakdown.sections[1].signal_note.startswith(
        "Recent form works against the under"
    )
    assert response.verdict.breakdown.sections[7].tone == "support"
    assert response.verdict.breakdown.sections[8].tone == "unavailable"
    assert response.verdict.reasons == [
        response.verdict.breakdown.sections[0].signal_note,
        response.verdict.breakdown.sections[1].signal_note,
        response.verdict.breakdown.sections[2].signal_note,
    ]
    assert "11.4% for going under" not in response.verdict.breakdown.sections[0].signal_note


@pytest.mark.asyncio
async def test_agent_chat_service_surfaces_line_moved_status():
    async def graph_runner(_query: str, _event_context: dict[str, object]):
        return _make_graph_result(
            decision="avoid",
            market_implied_probability=None,
            expected_value_pct=None,
            summary="The live market still exists, but the quoted line has moved away from the original pick.",
            data_quality_flags=["line_moved"],
            market_pricing_mode="line_moved",
            queried_line=28.5,
            best_line=27.5,
            available_lines=[27.5, 28.0],
            best_book="fanduel",
            best_odds=-108,
            eligible_for_bet=False,
        )

    service = AgentChatService(
        graph_runner=graph_runner
    )

    request = AgentChatRequest.model_validate(
        {
            "thread": "thread-line-moved",
            "message": "Summarize line movement",
            "action": "line_movement",
            "context": {
                "page": {"route": "/picks", "date": "2026-03-13"},
                "selected_pick": _make_pick(),
            },
        }
    )

    response = await service.handle_chat(request)

    assert response.status == "line_moved"
    assert response.verdict is not None
    assert response.verdict.market_pricing_mode == "line_moved"
    assert response.verdict.expected_value_pct is None
    assert response.verdict.market_implied_probability is None
    assert response.verdict.queried_line == 28.5
    assert response.verdict.best_line == 27.5
    assert response.verdict.available_lines == [27.5, 28.0]
    assert "line has moved" in response.reply.lower()


@pytest.mark.asyncio
async def test_agent_chat_service_marks_line_moved_and_missing_sections_in_breakdown():
    query_aligned_context = _make_query_aligned_context(
        query_side="under",
        threshold=4.5,
        historical_query_probability=0.82,
        historical_p_over=0.18,
        historical_p_under=0.82,
        historical_mean=3.25,
        historical_supports_query_side=True,
        recent_average=3.1,
        season_average=3.6,
        recent_minus_threshold=-1.4,
        trend_supports_query_side=True,
        signal_alignment="supports_query_side",
        pricing_mode="line_moved",
        market_query_probability=None,
        queried_line=4.5,
        best_line=5.0,
        available_lines=[5.0, 5.5],
        best_book="fanduel",
        best_odds=-108,
    )

    async def graph_runner(_query: str, _event_context: dict[str, object]):
        return _make_graph_result(
            decision="avoid",
            market_implied_probability=None,
            expected_value_pct=None,
            summary="The live market still exists, but the quoted line has moved away from the original pick.",
            data_quality_flags=["line_moved"],
            market_pricing_mode="line_moved",
            queried_line=4.5,
            best_line=5.0,
            available_lines=[5.0, 5.5],
            best_book="fanduel",
            best_odds=-108,
            eligible_for_bet=False,
            query_aligned_context=query_aligned_context,
        )

    service = AgentChatService(graph_runner=graph_runner)
    request = AgentChatRequest.model_validate(
        {
            "thread": "thread-line-moved-breakdown",
            "message": "Summarize line movement",
            "action": "line_movement",
            "context": {
                "page": {"route": "/picks", "date": "2026-03-13"},
                "selected_pick": _make_pick(direction="under", threshold=4.5),
            },
        }
    )

    response = await service.handle_chat(request)

    assert response.verdict is not None
    assert response.verdict.breakdown is not None
    sections = {section.key: section for section in response.verdict.breakdown.sections}
    assert sections["market"].tone == "caution"
    assert sections["market"].signal_note == (
        "The original 4.50 line is no longer available; the closest live line is 5.00."
    )
    assert sections["lineup"].tone == "unavailable"
    assert sections["projection"].tone == "unavailable"


@pytest.mark.asyncio
async def test_agent_chat_service_builds_under_reasons_from_query_aligned_context():
    query_aligned_context = _make_query_aligned_context(
        query_side="under",
        threshold=4.5,
        historical_query_probability=0.8864,
        historical_p_over=0.1136,
        historical_p_under=0.8864,
        historical_mean=2.98,
        historical_supports_query_side=True,
        recent_average=5.33,
        season_average=2.98,
        recent_minus_threshold=0.83,
        trend_supports_query_side=False,
        signal_alignment="against_query_side",
        pricing_mode="exact_line",
        market_query_probability=0.5323,
        queried_line=4.5,
        best_line=4.5,
        available_lines=[4.5],
        best_book="draftkings",
        best_odds=-110,
    )

    async def graph_runner(_query: str, _event_context: dict[str, object]):
        return _make_graph_result(
            decision="under",
            confidence=0.9,
            model_probability=0.8864,
            market_implied_probability=0.5323,
            expected_value_pct=0.6652,
            summary="Historical detail is wrong here on purpose, but the canonical summary still supports the under.",
            dimensions={
                "historical": {
                    "signal": "under",
                    "reliability": 0.9,
                    "detail": "Historical data shows a hit rate of 11.4% for going under.",
                },
            },
            query_aligned_context=query_aligned_context,
        )

    service = AgentChatService(graph_runner=graph_runner)
    request = AgentChatRequest.model_validate(
        {
            "thread": "thread-under-reasons",
            "message": "Should I bet this?",
            "action": "analyze_pick",
            "context": {
                "page": {"route": "/picks", "date": "2026-03-13"},
                "selected_pick": _make_pick(
                    player_name="Test Player",
                    metric="rebounds",
                    direction="under",
                    threshold=4.5,
                ),
            },
        }
    )

    response = await service.handle_chat(request)

    assert response.verdict is not None
    assert response.verdict.reasons[0] == (
        "Historical data gives 88.6% to go under, with a mean of 2.98 versus a 4.50 line."
    )
    assert response.verdict.reasons[1] == (
        "Recent form works against the under: last 5 average is 5.33, above the 4.50 line."
    )
    assert response.verdict.reasons[2] == (
        "Market prices the under at 53.2% on the 4.50 line, best price at DraftKings (-110)."
    )
    assert "11.4% for going under" not in response.verdict.reasons[0]


@pytest.mark.asyncio
async def test_agent_chat_service_uses_line_moved_reason_from_query_aligned_context():
    query_aligned_context = _make_query_aligned_context(
        query_side="under",
        threshold=4.5,
        historical_query_probability=0.82,
        historical_p_over=0.18,
        historical_p_under=0.82,
        historical_mean=3.25,
        historical_supports_query_side=True,
        recent_average=3.1,
        season_average=3.6,
        recent_minus_threshold=-1.4,
        trend_supports_query_side=True,
        signal_alignment="supports_query_side",
        pricing_mode="line_moved",
        market_query_probability=None,
        queried_line=4.5,
        best_line=5.0,
        available_lines=[5.0, 5.5],
        best_book="fanduel",
        best_odds=-108,
    )

    async def graph_runner(_query: str, _event_context: dict[str, object]):
        return _make_graph_result(
            decision="avoid",
            market_implied_probability=None,
            expected_value_pct=None,
            summary="The live market still exists, but the quoted line has moved away from the original pick.",
            data_quality_flags=["line_moved"],
            market_pricing_mode="line_moved",
            queried_line=4.5,
            best_line=5.0,
            available_lines=[5.0, 5.5],
            best_book="fanduel",
            best_odds=-108,
            eligible_for_bet=False,
            query_aligned_context=query_aligned_context,
        )

    service = AgentChatService(graph_runner=graph_runner)
    request = AgentChatRequest.model_validate(
        {
            "thread": "thread-line-moved-reasons",
            "message": "Summarize line movement",
            "action": "line_movement",
            "context": {
                "page": {"route": "/picks", "date": "2026-03-13"},
                "selected_pick": _make_pick(direction="under", threshold=4.5),
            },
        }
    )

    response = await service.handle_chat(request)

    assert response.verdict is not None
    assert (
        response.verdict.reasons[2]
        == "The original 4.50 line is no longer available; the closest live line is 5.00."
    )


@pytest.mark.asyncio
async def test_agent_chat_service_uses_market_unavailable_reason_from_query_aligned_context():
    query_aligned_context = _make_query_aligned_context(
        query_side="over",
        pricing_mode="unavailable",
        market_query_probability=None,
        best_line=None,
        available_lines=[],
        best_book=None,
        best_odds=None,
    )

    async def graph_runner(_query: str, _event_context: dict[str, object]):
        return _make_graph_result(
            decision="avoid",
            market_implied_probability=None,
            expected_value_pct=None,
            summary="There is not enough current market data to price this bet cleanly.",
            data_quality_flags=["no_market_data"],
            market_pricing_mode="unavailable",
            best_line=None,
            available_lines=[],
            best_book=None,
            best_odds=None,
            eligible_for_bet=False,
            query_aligned_context=query_aligned_context,
        )

    service = AgentChatService(graph_runner=graph_runner)
    request = AgentChatRequest.model_validate(
        {
            "thread": "thread-market-unavailable-reasons",
            "message": "Should I bet this?",
            "action": "analyze_pick",
            "context": {
                "page": {"route": "/picks", "date": "2026-03-13"},
                "selected_pick": _make_pick(),
            },
        }
    )

    response = await service.handle_chat(request)

    assert response.verdict is not None
    assert response.verdict.reasons[2] == (
        "No exact same-line market quote is available, so EV is not priced."
    )


@pytest.mark.asyncio
async def test_agent_chat_service_reviews_entire_bet_slip():
    captured_queries: list[str] = []

    async def graph_runner(query: str, _event_context: dict[str, object]):
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

    response = await service.handle_chat(request)

    assert response.status == "ok"
    assert response.slip_review is not None
    assert response.slip_review.keep_count == 1
    assert response.slip_review.remove_count == 1
    assert response.slip_review.items[0].recommendation == "keep"
    assert response.slip_review.items[1].recommendation == "remove"
    assert len(captured_queries) == 2


def test_agent_chat_endpoint_validates_action_and_uses_service(monkeypatch):
    from app.api import agent as agent_api

    with TestClient(app) as client:
        invalid_response = client.post(
            "/api/nba/agent/chat",
            json={"thread": "thread-4", "message": "hi", "action": "unknown"},
        )
        assert invalid_response.status_code == 422

        async def fake_handle_chat(request: AgentChatRequest):
            async def graph_runner(_query: str, _event_context: dict[str, object]):
                return _make_graph_result()

            return await AgentChatService(
                graph_runner=graph_runner
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
