"""SPO-52 Phase 5b — unit tests for league-awareness across five product
agent nodes (historical, projection, market, critic, synthesizer) plus the
two prompt builders that sit underneath the critic/synth LLM calls.

Tested behaviour:
  1. `_build_critic_system("nba")`   is byte-identical to the pre-5b
     `_CRITIC_SYSTEM` constant (regression gate from SPO-52 acceptance).
  2. `_build_synthesizer_system("nba")` is byte-identical to `_SYNTH_SYSTEM`.
  3. WNBA versions of both prompts contain the literal "WNBA" plus all
     three context markers (40-min games, May–October, 11–12 players).
  4. All five league-aware nodes (`historical_agent`, `projection_agent`,
     `market_agent`, `critic`, `synthesizer`) return `state["league"]` in
     their partial state AND stamp it into their `audit_log` entry, for
     both NBA-default (state.league omitted → DEFAULT_LEAGUE) and WNBA
     paths.
  5. The critic + synthesizer nodes select the correct prompt for each
     league (verified by capturing the SystemMessage content the FakeLLM
     received).

Tool functions are not under test here — they are stubbed via monkeypatch
so the unit test surface stays scoped to league plumbing.
"""

from typing import Any, Dict, List

import pytest

import agents as agent_module
from state import DEFAULT_LEAGUE


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _CapturingFakeLLM:
    """Records the system-message content of every ainvoke call.

    Lets us assert that `_build_critic_system(league)` / `_build_synthesizer_system(league)`
    actually flowed into the LLM call, without coupling to LangChain
    message object equality.
    """

    def __init__(self, response_content: str = "{}") -> None:
        self._response = response_content
        self.captured_system: List[str] = []

    async def ainvoke(self, messages):  # type: ignore[no-untyped-def]
        # Conventional order: [SystemMessage, HumanMessage]
        self.captured_system.append(messages[0].content)
        return _FakeResponse(self._response)


# Safe, league-agnostic stub return; satisfies every `.get("details", {})`
# / `.get("signal")` lookup the heavy nodes perform without claiming
# anything substantive about the data.
_SAFE_TOOL_RETURN: Dict[str, Any] = {
    "status": "ok",
    "signal": "neutral",
    "details": {},
    "sample_size": 0,
}


def _sync_stub(*_args, **_kwargs):  # type: ignore[no-untyped-def]
    return _SAFE_TOOL_RETURN


async def _async_stub(*_args, **_kwargs):  # type: ignore[no-untyped-def]
    return _SAFE_TOOL_RETURN


@pytest.fixture
def stub_all_tools(monkeypatch):
    """Replace every tool the heavy nodes import into `agents` with a
    cheap return.  Names mirror the import block at the top of agents.py;
    keep these lists in sync if that import block changes."""
    sync_historical = [
        "get_base_stats", "get_role_conditioned_base_stats",
        "get_starter_bench_split", "get_opponent_history",
        "get_trend_analysis", "get_streak_info", "get_minutes_role_trend",
        "get_shooting_profile", "get_variance_profile",
        "get_schedule_context", "get_game_script_splits",
        # ⚠️ auto_teammate_impact is sync but `historical_agent_node`
        # wraps it in `asyncio.to_thread(...)`. A sync stub is still
        # correct because to_thread accepts any callable.
        "auto_teammate_impact",
    ]
    async_historical = [
        "get_official_injury_report",
        "get_projected_lineup_consensus",
        "get_player_lineup_context",
    ]
    sync_projection = [
        "get_full_projection", "calculate_edge",
        "get_opponent_defense_profile", "get_minutes_confidence",
    ]
    async_market = [
        "get_current_market", "get_line_movement", "get_best_price",
        "get_market_quote_for_line", "get_bookmaker_spread",
    ]

    for name in sync_historical + sync_projection:
        monkeypatch.setattr(agent_module, name, _sync_stub)
    for name in async_historical + async_market:
        monkeypatch.setattr(agent_module, name, _async_stub)


def _parsed_query_stub() -> Dict[str, Any]:
    return {
        "player": "Test Player",
        "metric": "points",
        "threshold": 10.5,
        "date": "",
        "opponent": "",
        "direction": "over",
        "event_id": "",
    }


# ===========================================================================
# 1–3. Prompt builder behaviour
# ===========================================================================

def test_critic_system_nba_is_byte_identical_to_legacy_constant():
    """SPO-52 regression gate: NBA path must produce the pre-5b prompt
    verbatim so the SPO-25 NBA golden flow is unaffected.
    Comparing against the module's own `_CRITIC_SYSTEM` constant — that
    constant is the frozen pre-5b text and is what `_build_critic_system`
    returns by reference on the NBA branch."""
    assert agent_module._build_critic_system("nba") == agent_module._CRITIC_SYSTEM


def test_synth_system_nba_is_byte_identical_to_legacy_constant():
    assert agent_module._build_synthesizer_system("nba") == agent_module._SYNTH_SYSTEM


def test_critic_system_wnba_contains_league_label_and_context_markers():
    prompt = agent_module._build_critic_system("wnba")
    # League label swap
    assert "a WNBA player-prop betting advisor" in prompt
    assert "an NBA player-prop betting advisor" not in prompt
    # Required WNBA context block markers
    assert "40 minutes" in prompt
    assert "May" in prompt and "October" in prompt
    assert "11–12 players" in prompt or "12 players" in prompt
    # And the original direction-context wording is preserved
    assert "query_aligned_context" in prompt


def test_synth_system_wnba_contains_league_label_and_context_markers():
    prompt = agent_module._build_synthesizer_system("wnba")
    assert "a WNBA player-prop betting advisor" in prompt
    assert "an NBA player-prop betting advisor" not in prompt
    assert "40 minutes" in prompt
    assert "May" in prompt and "October" in prompt
    assert "11–12 players" in prompt or "12 players" in prompt
    # Synthesizer-specific contract preserved
    assert "model_probability" in prompt


# ===========================================================================
# 4. League threading through the three "tool agent" nodes
# ===========================================================================

@pytest.mark.asyncio
async def test_historical_agent_defaults_league_to_nba_when_unset(stub_all_tools):
    """Legacy callers that don't set state.league (e.g. backtest harnesses,
    scripts/agents/cli.py before 5a) must still produce a league-tagged
    audit entry; the default lives on the read side per the SPO-48 design."""
    out = await agent_module.historical_agent_node(
        {"parsed_query": _parsed_query_stub(), "event_context": {}, "audit_log": []}
    )
    assert out["league"] == DEFAULT_LEAGUE == "nba"
    assert out["audit_log"][-1]["league"] == "nba"


@pytest.mark.asyncio
async def test_historical_agent_propagates_wnba(stub_all_tools):
    out = await agent_module.historical_agent_node(
        {
            "parsed_query": _parsed_query_stub(),
            "event_context": {},
            "audit_log": [],
            "league": "wnba",
        }
    )
    assert out["league"] == "wnba"
    assert out["audit_log"][-1]["league"] == "wnba"


def test_projection_agent_defaults_league_to_nba(stub_all_tools):
    out = agent_module.projection_agent_node(
        {"parsed_query": _parsed_query_stub(), "audit_log": []}
    )
    assert out["league"] == "nba"
    assert out["audit_log"][-1]["league"] == "nba"


def test_projection_agent_propagates_wnba(stub_all_tools):
    out = agent_module.projection_agent_node(
        {"parsed_query": _parsed_query_stub(), "audit_log": [], "league": "wnba"}
    )
    assert out["league"] == "wnba"
    assert out["audit_log"][-1]["league"] == "wnba"


@pytest.mark.asyncio
async def test_market_agent_defaults_league_to_nba(stub_all_tools):
    out = await agent_module.market_agent_node(
        {"parsed_query": _parsed_query_stub(), "audit_log": []}
    )
    assert out["league"] == "nba"
    assert out["audit_log"][-1]["league"] == "nba"


@pytest.mark.asyncio
async def test_market_agent_propagates_wnba(stub_all_tools):
    out = await agent_module.market_agent_node(
        {"parsed_query": _parsed_query_stub(), "audit_log": [], "league": "wnba"}
    )
    assert out["league"] == "wnba"
    assert out["audit_log"][-1]["league"] == "wnba"


# ===========================================================================
# 5. Critic + Synthesizer: league threading AND correct prompt selection
# ===========================================================================

@pytest.mark.asyncio
async def test_critic_node_defaults_to_nba_prompt(monkeypatch):
    fake = _CapturingFakeLLM(response_content='{"risk_factors": [], "risk_grade": "low", "reasoning": "ok"}')
    monkeypatch.setattr(agent_module, "_get_llm", lambda: fake)
    out = await agent_module.critic_node(
        {"scorecard": {}, "historical_signals": {}, "market_signals": {}, "audit_log": []}
    )
    assert out["league"] == "nba"
    assert out["audit_log"][-1]["league"] == "nba"
    # Prompt picked == NBA prompt (= byte-identical legacy constant)
    assert fake.captured_system == [agent_module._CRITIC_SYSTEM]


@pytest.mark.asyncio
async def test_critic_node_selects_wnba_prompt_when_league_set(monkeypatch):
    fake = _CapturingFakeLLM(response_content='{"risk_factors": [], "risk_grade": "low", "reasoning": "ok"}')
    monkeypatch.setattr(agent_module, "_get_llm", lambda: fake)
    out = await agent_module.critic_node(
        {
            "scorecard": {}, "historical_signals": {}, "market_signals": {},
            "audit_log": [], "league": "wnba",
        }
    )
    assert out["league"] == "wnba"
    assert out["audit_log"][-1]["league"] == "wnba"
    # 💡 Single-call invariant: we expect exactly one LLM call per node;
    # asserting list length defends against accidental retries that would
    # double-charge OpenAI in production.
    assert len(fake.captured_system) == 1
    assert "a WNBA player-prop betting advisor" in fake.captured_system[0]
    assert "40 minutes" in fake.captured_system[0]


@pytest.mark.asyncio
async def test_synthesizer_node_defaults_to_nba_prompt(monkeypatch):
    fake = _CapturingFakeLLM(response_content='{"decision": "avoid", "confidence": 0.0, "summary": "", "needs_retry": false}')
    monkeypatch.setattr(agent_module, "_get_llm", lambda: fake)
    out = await agent_module.synthesizer_node(
        {
            "scorecard": {"decision": "avoid"},
            "historical_signals": {}, "market_signals": {}, "projection_signals": {},
            "critic_notes": [], "audit_log": [], "iteration": 0,
        }
    )
    assert out["league"] == "nba"
    assert out["audit_log"][-1]["league"] == "nba"
    assert fake.captured_system == [agent_module._SYNTH_SYSTEM]


@pytest.mark.asyncio
async def test_synthesizer_node_selects_wnba_prompt_when_league_set(monkeypatch):
    fake = _CapturingFakeLLM(response_content='{"decision": "avoid", "confidence": 0.0, "summary": "", "needs_retry": false}')
    monkeypatch.setattr(agent_module, "_get_llm", lambda: fake)
    out = await agent_module.synthesizer_node(
        {
            "scorecard": {"decision": "avoid"},
            "historical_signals": {}, "market_signals": {}, "projection_signals": {},
            "critic_notes": [], "audit_log": [], "iteration": 0,
            "league": "wnba",
        }
    )
    assert out["league"] == "wnba"
    assert out["audit_log"][-1]["league"] == "wnba"
    assert len(fake.captured_system) == 1
    assert "a WNBA player-prop betting advisor" in fake.captured_system[0]
    assert "40 minutes" in fake.captured_system[0]
