import os
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
AGENTS_DIR = PROJECT_ROOT / "scripts" / "agents"

for path in (str(BACKEND_DIR), str(PROJECT_ROOT), str(AGENTS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from scripts.agents import agents as agents_module
from scripts.agents.scoring import compute_scorecard
from scripts.agents.tools import historical as historical_tools


def _market_signals(query_probability: float = 0.48, queried_line: float = 25.5) -> dict:
    return {
        "get_current_market": {
            "signal": "neutral",
            "effect_size": 0.0,
            "sample_size": 2,
            "reliability": 0.3,
            "window": "today",
            "source": "test",
            "details": {
                "n_books": 2,
            },
        },
        "get_market_quote_for_line": {
            "signal": "neutral",
            "effect_size": 0.0,
            "sample_size": 2,
            "reliability": 0.3,
            "window": "today",
            "source": "test",
            "details": {
                "pricing_mode": "exact_line",
                "queried_line": queried_line,
                "available_lines": [queried_line],
                "market_implied_for_query": query_probability,
                "best_book": "testbook",
                "best_line": queried_line,
                "best_odds": -110,
            },
        },
    }


def _historical_signals(
    *,
    base_rate: float = 0.52,
    base_mean: float = 26.0,
    role_rate: float | None = None,
    role_mean: float | None = None,
    role_sample_size: int = 12,
    role_reliability: float = 0.7,
    player_is_projected_starter: bool | None = None,
    lineup_confidence: str = "high",
    source_disagreement: bool = False,
    freshness_risk: bool = False,
) -> dict:
    signals = {
        "get_base_stats": {
            "signal": "neutral",
            "effect_size": round(base_mean - 25.5, 4),
            "sample_size": 40,
            "reliability": 0.9,
            "window": "season",
            "source": "csv",
            "details": {
                "shrunk_rate": base_rate,
                "mean": base_mean,
                "median": base_mean,
                "std": 4.2,
                "hit_rate": base_rate,
                "over_count": int(round(base_rate * 40)),
                "total": 40,
            },
        },
        "get_trend_analysis": {
            "signal": "neutral",
            "effect_size": 0.0,
            "sample_size": 20,
            "reliability": 0.8,
            "window": "last_20",
            "source": "csv",
            "details": {
                "rolling_averages": {"last_5": base_mean},
                "season_avg": base_mean,
                "recent_vs_season_pct": 0.0,
            },
        },
        "get_shooting_profile": {
            "signal": "neutral",
            "effect_size": 0.0,
            "sample_size": 20,
            "reliability": 0.8,
            "window": "season",
            "source": "csv",
            "details": {"fg_diff": 0.0},
        },
        "get_variance_profile": {
            "signal": "neutral",
            "effect_size": 0.0,
            "sample_size": 40,
            "reliability": 0.8,
            "window": "season",
            "source": "csv",
            "details": {"cv": 0.2},
        },
        "get_schedule_context": {
            "signal": "neutral",
            "effect_size": 0.0,
            "sample_size": 10,
            "reliability": 0.8,
            "window": "season",
            "source": "csv",
            "details": {"is_back_to_back": False},
        },
        "auto_teammate_impact": {
            "signal": "neutral",
            "effect_size": 0.0,
            "sample_size": 10,
            "reliability": 0.8,
            "window": "season",
            "source": "csv",
            "details": {"teammate_chemistry": [], "team": "BOS"},
        },
        "get_own_team_injury_report": {
            "signal": "neutral",
            "effect_size": 0.0,
            "sample_size": 0,
            "reliability": 0.8,
            "window": "today",
            "source": "test",
            "details": {"injuries": []},
        },
        "get_player_lineup_context": {
            "signal": "neutral",
            "effect_size": 0.0,
            "sample_size": 5,
            "reliability": 0.8,
            "window": "today",
            "source": "test",
            "details": {
                "player_is_projected_starter": player_is_projected_starter,
                "source_disagreement": source_disagreement,
                "freshness_risk": freshness_risk,
                "confidence": lineup_confidence,
            },
        },
        "get_own_team_projected_lineup": {
            "signal": "neutral",
            "effect_size": 0.0,
            "sample_size": 5,
            "reliability": 0.8,
            "window": "today",
            "source": "test",
            "details": {
                "team": "BOS",
                "status": "projected",
                "confidence": lineup_confidence,
                "source_disagreement": source_disagreement,
                "updated_at": "2026-03-16T20:00:00Z",
                "starters": ["Player A", "Player B", "Player C", "Player D", "Player E"],
            },
        },
        "get_opponent_projected_lineup": {
            "signal": "neutral",
            "effect_size": 0.0,
            "sample_size": 5,
            "reliability": 0.8,
            "window": "today",
            "source": "test",
            "details": {
                "team": "LAL",
                "status": "projected",
                "confidence": lineup_confidence,
                "source_disagreement": False,
                "updated_at": "2026-03-16T20:00:00Z",
                "starters": ["Opp A", "Opp B", "Opp C", "Opp D", "Opp E"],
            },
        },
    }
    if role_rate is not None and role_mean is not None and player_is_projected_starter is not None:
        role = "starter" if player_is_projected_starter else "bench"
        role_label = "projected_starter" if player_is_projected_starter else "projected_bench"
        signals["get_role_conditioned_base_stats"] = {
            "signal": "over" if role_rate >= 0.58 else ("under" if role_rate <= 0.42 else "neutral"),
            "effect_size": round(role_mean - 25.5, 4),
            "sample_size": role_sample_size,
            "reliability": role_reliability,
            "window": "season",
            "source": "csv",
            "details": {
                "shrunk_rate": role_rate,
                "mean": role_mean,
                "median": role_mean,
                "std": 4.0,
                "hit_rate": role_rate,
                "over_count": int(round(role_rate * role_sample_size)),
                "total": role_sample_size,
                "role": role,
                "role_label": role_label,
                "minimum_role_sample": 4,
            },
        }
    return signals


def _stub_signal(**details):
    return {
        "signal": "neutral",
        "effect_size": 0.0,
        "sample_size": 10,
        "reliability": 0.8,
        "window": "season",
        "source": "test",
        "details": details,
    }


def test_get_role_conditioned_base_stats_filters_starter_and_bench_games(monkeypatch):
    games = [
        {"points": 24, "minutes": 31, "is_starter": True},
        {"points": 21, "minutes": 32, "is_starter": True},
        {"points": 19, "minutes": 30, "is_starter": True},
        {"points": 27, "minutes": 34, "is_starter": True},
        {"points": 12, "minutes": 19, "is_starter": False},
        {"points": 14, "minutes": 20, "is_starter": False},
        {"points": 11, "minutes": 17, "is_starter": False},
    ]
    monkeypatch.setattr(historical_tools, "_games_for", lambda player, n=0: games)

    starter = historical_tools.get_role_conditioned_base_stats("Test Player", "points", 18.5, True)
    bench = historical_tools.get_role_conditioned_base_stats("Test Player", "points", 18.5, False)

    assert starter["sample_size"] == 4
    assert starter["details"]["role"] == "starter"
    assert starter["details"]["role_label"] == "projected_starter"
    assert starter["details"]["minimum_role_sample"] == 4
    assert starter["details"]["over_count"] == 4
    assert starter["details"]["total"] == 4
    assert starter["details"]["mean"] == 22.75

    assert bench["sample_size"] == 3
    assert bench["details"]["role"] == "bench"
    assert bench["details"]["role_label"] == "projected_bench"
    assert bench["details"]["minimum_role_sample"] == 4
    assert bench["details"]["over_count"] == 0
    assert bench["details"]["total"] == 3
    assert bench["details"]["mean"] == 12.33


def test_get_role_conditioned_base_stats_returns_unavailable_when_role_unknown():
    result = historical_tools.get_role_conditioned_base_stats("Test Player", "points", 18.5, None)

    assert result["signal"] == "unavailable"
    assert "role is unknown" in result["details"]["error"]


def test_compute_scorecard_role_blend_pushes_projected_starter_toward_over():
    baseline = compute_scorecard(
        historical_signals=_historical_signals(player_is_projected_starter=True),
        projection_signals={},
        market_signals=_market_signals(),
        direction="over",
    )
    starter = compute_scorecard(
        historical_signals=_historical_signals(
            role_rate=0.82,
            role_mean=31.0,
            player_is_projected_starter=True,
        ),
        projection_signals={},
        market_signals=_market_signals(),
        direction="over",
    )

    assert baseline["decision"] == "avoid"
    assert starter["decision"] == "over"
    assert starter["model_probability"] > baseline["model_probability"]
    assert starter["query_aligned_context"]["historical"]["mode"] == "role_blended"
    assert starter["query_aligned_context"]["historical"]["role"] == "starter"
    assert starter["query_aligned_context"]["historical"]["role_weight"] == 0.85
    assert starter["adjustments"]["base_rate_over_all_games"] == 0.52
    assert starter["adjustments"]["base_rate_over_role"] == 0.82
    assert starter["adjustments"]["base_rate_over_blended"] > 0.52


def test_compute_scorecard_role_blend_pushes_projected_bench_toward_under():
    baseline = compute_scorecard(
        historical_signals=_historical_signals(player_is_projected_starter=False),
        projection_signals={},
        market_signals=_market_signals(),
        direction="over",
    )
    bench = compute_scorecard(
        historical_signals=_historical_signals(
            role_rate=0.22,
            role_mean=18.0,
            player_is_projected_starter=False,
        ),
        projection_signals={},
        market_signals=_market_signals(),
        direction="over",
    )

    assert baseline["decision"] == "avoid"
    assert bench["decision"] == "under"
    assert bench["model_probability"] < baseline["model_probability"]
    assert "player_not_in_projected_starting_lineup" in bench["data_quality_flags"]
    assert bench["query_aligned_context"]["historical"]["mode"] == "role_blended"
    assert bench["query_aligned_context"]["historical"]["role"] == "bench"
    assert bench["adjustments"]["base_rate_over_role"] == 0.22


def test_compute_scorecard_ignores_role_signal_when_sample_is_below_minimum():
    scorecard = compute_scorecard(
        historical_signals=_historical_signals(
            role_rate=0.82,
            role_mean=31.0,
            role_sample_size=3,
            player_is_projected_starter=True,
        ),
        projection_signals={},
        market_signals=_market_signals(),
        direction="over",
    )

    assert scorecard["decision"] == "avoid"
    assert scorecard["model_probability"] == 0.52
    assert scorecard["query_aligned_context"]["historical"]["mode"] == "all_games"
    assert scorecard["query_aligned_context"]["historical"]["role_weight"] == 0.0
    assert scorecard["adjustments"]["base_rate_over_blended"] == 0.52


def test_compute_scorecard_prefers_raw_hit_rate_over_shrunk_rate_for_user_facing_history():
    historical_signals = _historical_signals(base_rate=0.52, base_mean=26.0)
    historical_signals["get_base_stats"]["details"]["hit_rate"] = 0.66
    historical_signals["get_base_stats"]["details"]["shrunk_rate"] = 0.621

    scorecard = compute_scorecard(
        historical_signals=historical_signals,
        projection_signals={},
        market_signals=_market_signals(),
        direction="under",
    )

    assert scorecard["query_aligned_context"]["historical"]["p_over"] == 0.66
    assert scorecard["query_aligned_context"]["historical"]["p_under"] == 0.34
    assert scorecard["query_aligned_context"]["historical"]["query_probability"] == 0.34
    assert scorecard["adjustments"]["base_rate_over_all_games"] == 0.66
    assert scorecard["adjustments"]["base_rate_over_blended"] == 0.66


def test_compute_scorecard_reduces_role_weight_when_lineup_quality_is_degraded():
    scorecard = compute_scorecard(
        historical_signals=_historical_signals(
            role_rate=0.82,
            role_mean=31.0,
            player_is_projected_starter=True,
            source_disagreement=True,
        ),
        projection_signals={},
        market_signals=_market_signals(),
        direction="over",
    )

    assert scorecard["query_aligned_context"]["historical"]["mode"] == "role_blended"
    assert scorecard["query_aligned_context"]["historical"]["role_weight"] == 0.425
    assert scorecard["adjustments"]["role_weight"] == 0.425
    assert "lineup_sources_disagree" in scorecard["data_quality_flags"]


@pytest.mark.asyncio
@pytest.mark.parametrize("player_is_projected_starter", [True, False])
async def test_historical_agent_node_adds_role_conditioned_signal_when_role_is_known(
    monkeypatch,
    player_is_projected_starter,
):
    captured: dict[str, object] = {}

    def fake_role_conditioned(player: str, metric: str, threshold: float, is_starter: bool, n: int = 0):
        captured["args"] = (player, metric, threshold, is_starter, n)
        return _stub_signal(
            shrunk_rate=0.6,
            mean=24.0,
            median=24.0,
            std=3.0,
            hit_rate=0.6,
            over_count=6,
            total=10,
            role="starter" if is_starter else "bench",
            role_label="projected_starter" if is_starter else "projected_bench",
            minimum_role_sample=4,
        )

    monkeypatch.setattr(agents_module, "get_base_stats", lambda *args, **kwargs: _stub_signal(shrunk_rate=0.5, mean=20.0))
    monkeypatch.setattr(agents_module, "get_starter_bench_split", lambda *args, **kwargs: _stub_signal())
    monkeypatch.setattr(agents_module, "get_opponent_history", lambda *args, **kwargs: _stub_signal())
    monkeypatch.setattr(agents_module, "get_trend_analysis", lambda *args, **kwargs: _stub_signal())
    monkeypatch.setattr(agents_module, "get_streak_info", lambda *args, **kwargs: _stub_signal())
    monkeypatch.setattr(agents_module, "get_minutes_role_trend", lambda *args, **kwargs: _stub_signal())
    monkeypatch.setattr(agents_module, "get_shooting_profile", lambda *args, **kwargs: _stub_signal())
    monkeypatch.setattr(agents_module, "get_variance_profile", lambda *args, **kwargs: _stub_signal(cv=0.2))
    monkeypatch.setattr(agents_module, "get_schedule_context", lambda *args, **kwargs: _stub_signal(is_back_to_back=False))
    monkeypatch.setattr(agents_module, "get_game_script_splits", lambda *args, **kwargs: _stub_signal())
    monkeypatch.setattr(agents_module, "auto_teammate_impact", lambda *args, **kwargs: _stub_signal(team="BOS", teammate_chemistry=[]))
    monkeypatch.setattr(agents_module, "get_role_conditioned_base_stats", fake_role_conditioned)

    async def fake_injury_report(*args, **kwargs):
        return _stub_signal(team="BOS", injuries=[])

    async def fake_projected_lineup(team: str, date: str = ""):
        return _stub_signal(team=team, status="projected", confidence="high", source_disagreement=False, starters=[])

    async def fake_player_lineup_context(*args, **kwargs):
        return _stub_signal(
            player_is_projected_starter=player_is_projected_starter,
            freshness_risk=False,
            source_disagreement=False,
            confidence="high",
        )

    monkeypatch.setattr(agents_module, "get_official_injury_report", fake_injury_report)
    monkeypatch.setattr(agents_module, "get_projected_lineup_consensus", fake_projected_lineup)
    monkeypatch.setattr(agents_module, "get_player_lineup_context", fake_player_lineup_context)

    result = await agents_module.historical_agent_node(
        {
            "parsed_query": {
                "player": "Test Player",
                "metric": "points",
                "threshold": 25.5,
                "date": "2026-03-16",
                "opponent": "LAL",
            },
            "event_context": {},
        }
    )

    assert "get_role_conditioned_base_stats" in result["historical_signals"]
    assert captured["args"] == ("Test Player", "points", 25.5, player_is_projected_starter, 0)


@pytest.mark.asyncio
async def test_historical_agent_node_skips_role_conditioned_signal_when_role_is_unknown(monkeypatch):
    monkeypatch.setattr(agents_module, "get_base_stats", lambda *args, **kwargs: _stub_signal(shrunk_rate=0.5, mean=20.0))
    monkeypatch.setattr(agents_module, "get_starter_bench_split", lambda *args, **kwargs: _stub_signal())
    monkeypatch.setattr(agents_module, "get_opponent_history", lambda *args, **kwargs: _stub_signal())
    monkeypatch.setattr(agents_module, "get_trend_analysis", lambda *args, **kwargs: _stub_signal())
    monkeypatch.setattr(agents_module, "get_streak_info", lambda *args, **kwargs: _stub_signal())
    monkeypatch.setattr(agents_module, "get_minutes_role_trend", lambda *args, **kwargs: _stub_signal())
    monkeypatch.setattr(agents_module, "get_shooting_profile", lambda *args, **kwargs: _stub_signal())
    monkeypatch.setattr(agents_module, "get_variance_profile", lambda *args, **kwargs: _stub_signal(cv=0.2))
    monkeypatch.setattr(agents_module, "get_schedule_context", lambda *args, **kwargs: _stub_signal(is_back_to_back=False))
    monkeypatch.setattr(agents_module, "get_game_script_splits", lambda *args, **kwargs: _stub_signal())
    monkeypatch.setattr(agents_module, "auto_teammate_impact", lambda *args, **kwargs: _stub_signal(team="BOS", teammate_chemistry=[]))
    monkeypatch.setattr(
        agents_module,
        "get_role_conditioned_base_stats",
        lambda *args, **kwargs: pytest.fail("role-conditioned tool should not run when lineup role is unknown"),
    )

    async def fake_injury_report(*args, **kwargs):
        return _stub_signal(team="BOS", injuries=[])

    async def fake_projected_lineup(team: str, date: str = ""):
        return _stub_signal(team=team, status="projected", confidence="high", source_disagreement=False, starters=[])

    async def fake_player_lineup_context(*args, **kwargs):
        return _stub_signal(
            player_is_projected_starter=None,
            freshness_risk=False,
            source_disagreement=False,
            confidence="high",
        )

    monkeypatch.setattr(agents_module, "get_official_injury_report", fake_injury_report)
    monkeypatch.setattr(agents_module, "get_projected_lineup_consensus", fake_projected_lineup)
    monkeypatch.setattr(agents_module, "get_player_lineup_context", fake_player_lineup_context)

    result = await agents_module.historical_agent_node(
        {
            "parsed_query": {
                "player": "Test Player",
                "metric": "points",
                "threshold": 25.5,
                "date": "2026-03-16",
                "opponent": "LAL",
            },
            "event_context": {},
        }
    )

    assert "get_role_conditioned_base_stats" not in result["historical_signals"]
