"""
agents.py – 6 LLM agent definitions for the betting advisor graph.

Each agent is a function that takes BettingState and returns partial state updates.
LLMs handle query parsing, tool planning, contradiction analysis, and explanation.
Deterministic code handles scoring (see scoring.py).

Agent list:
  1. Planner          – parse user query, decide which paths to invoke
  2. Historical Agent  – run Dimension 1-5 tools
  3. Projection Agent  – run Dimension 6 stubs
  4. Market Agent      – run Dimension 7 tools
  5. Critic            – attack the scorecard
  6. Synthesizer       – explain the deterministic result
"""

import json
import os
import sys
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_AGENTS_DIR, "..", ".."))
if _AGENTS_DIR not in sys.path:
    sys.path.insert(0, _AGENTS_DIR)
if os.path.join(_PROJECT_ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "backend"))

from date_utils import normalize_date
from tools.historical import (
    get_base_stats, get_starter_bench_split, get_opponent_history,
    get_trend_analysis, get_streak_info, get_minutes_role_trend,
    get_shooting_profile, get_variance_profile,
    get_schedule_context, get_game_script_splits,
    auto_teammate_impact, get_official_injury_report,
)
from tools.projection import (
    get_full_projection, calculate_edge,
    get_opponent_defense_profile, get_minutes_confidence,
)
from tools.market import (
    get_current_market, get_line_movement,
    get_best_price, get_market_quote_for_line, get_bookmaker_spread,
)
from scoring import compute_scorecard

# ---------------------------------------------------------------------------
# LLM instance (lazy-initialized to avoid import-time API key errors)
# ---------------------------------------------------------------------------
_LLM = None

def _get_llm():
    global _LLM
    if _LLM is None:
        _LLM = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
    return _LLM

# ===================================================================
# 1. PLANNER
# ===================================================================

_PLANNER_SYSTEM = """\
You are the Planner of an NBA player-prop betting advisor.

Given a user query, extract structured fields and output ONLY valid JSON:
{
  "player": "<full player name>",
  "metric": "points | assists | rebounds | pra",
  "threshold": <number>,
  "date": "<YYYY-MM-DD or empty>",
  "opponent": "<team name or empty>",
  "direction": "over | under | any",
  "needs_market": true | false,
  "needs_historical": true,
  "needs_projection": false,
  "comparison_players": []
}

Rules:
- If the user mentions a bet recommendation, set needs_market=true.
- projection is always false (dummy data).
- If no threshold is explicit, set threshold to 0 and note it must come from the market line.
- If the user says "tomorrow" (or typos like "tommorow"), set date to tomorrow's date in YYYY-MM-DD (e.g. 2025-03-13) so market tools can fetch that day's odds.
- Return ONLY the JSON object, no extra text.
"""


def planner_node(state: Dict[str, Any]) -> Dict[str, Any]:
    query = state.get("user_query", "")
    resp = _get_llm().invoke([
        SystemMessage(content=_PLANNER_SYSTEM),
        HumanMessage(content=query),
    ])
    text = resp.content.strip()

    # Parse JSON from response
    try:
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {
            "player": "", "metric": "points", "threshold": 0,
            "date": "", "opponent": "", "direction": "any",
            "needs_market": True, "needs_historical": True,
            "needs_projection": False, "comparison_players": [],
            "parse_error": text,
        }

    # 將 "tomorrow"/"today" 等口語轉成 YYYY-MM-DD（本地時區），供各 tool 使用
    raw_date = parsed.get("date", "")
    if raw_date:
        parsed["date"] = normalize_date(raw_date)

    return {
        "parsed_query": parsed,
        "availability": {
            "historical": parsed.get("needs_historical", True),
            "projection": False,
            "market": parsed.get("needs_market", True),
        },
        "audit_log": state.get("audit_log", []) + [{"node": "planner", "output": parsed}],
    }


# ===================================================================
# 2. HISTORICAL + OPPORTUNITY AGENT
# ===================================================================

def historical_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    pq = state.get("parsed_query", {})
    player = pq.get("player", "")
    metric = pq.get("metric", "points")
    threshold = pq.get("threshold", 0)
    date = pq.get("date", "")
    opponent = pq.get("opponent", "")

    signals: Dict[str, Any] = {}

    signals["get_base_stats"] = get_base_stats(player, metric, threshold)
    signals["get_starter_bench_split"] = get_starter_bench_split(player, metric, threshold)

    if opponent:
        signals["get_opponent_history"] = get_opponent_history(player, metric, threshold, opponent)

    signals["get_trend_analysis"] = get_trend_analysis(player, metric)
    signals["get_streak_info"] = get_streak_info(player, metric, threshold)
    signals["get_minutes_role_trend"] = get_minutes_role_trend(player)
    signals["get_shooting_profile"] = get_shooting_profile(player)
    signals["get_variance_profile"] = get_variance_profile(player, metric)
    signals["get_schedule_context"] = get_schedule_context(player, date)
    signals["get_game_script_splits"] = get_game_script_splits(player, metric, threshold)
    signals["auto_teammate_impact"] = auto_teammate_impact(player, metric, threshold)

    # Fetch injury report for the player's OWN team (not the opponent).
    # auto_teammate_impact already does this internally, but we also surface
    # the raw report so the Critic and Synthesizer can reference it directly.
    own_team = signals["auto_teammate_impact"].get("details", {}).get("team", "")
    signals["get_own_team_injury_report"] = get_official_injury_report(
        own_team or "unknown", date, player=player
    )

    # Also fetch opponent injury report if we know the opponent
    if opponent:
        signals["get_opponent_injury_report"] = get_official_injury_report(
            opponent, date
        )

    return {
        "historical_signals": signals,
        "audit_log": state.get("audit_log", []) + [{"node": "historical_agent", "tools_run": list(signals.keys())}],
    }


# ===================================================================
# 3. PROJECTION AGENT (stub)
# ===================================================================

def projection_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    pq = state.get("parsed_query", {})
    player = pq.get("player", "")
    date = pq.get("date", "")
    threshold = pq.get("threshold", 0)

    signals = {
        "get_full_projection": get_full_projection(player, date),
        "calculate_edge": calculate_edge(0, threshold),
        "get_opponent_defense_profile": get_opponent_defense_profile(player, date),
        "get_minutes_confidence": get_minutes_confidence(player, date),
    }

    return {
        "projection_signals": signals,
        "audit_log": state.get("audit_log", []) + [{"node": "projection_agent", "status": "all_unavailable"}],
    }


# ===================================================================
# 4. MARKET AGENT
# ===================================================================

def market_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    pq = state.get("parsed_query", {})
    player = pq.get("player", "")
    metric = pq.get("metric", "points")
    threshold = pq.get("threshold", 0)
    date = pq.get("date", "")
    direction = pq.get("direction", "over")

    signals: Dict[str, Any] = {}
    signals["get_current_market"] = get_current_market(player, metric, date)
    signals["get_line_movement"] = get_line_movement(player, metric, date)
    signals["get_best_price"] = get_best_price(player, metric, direction, date)
    signals["get_market_quote_for_line"] = get_market_quote_for_line(
        player, metric, threshold, direction, date
    )
    signals["get_bookmaker_spread"] = get_bookmaker_spread(player, metric, date)

    return {
        "market_signals": signals,
        "audit_log": state.get("audit_log", []) + [{"node": "market_agent", "tools_run": list(signals.keys())}],
    }


# ===================================================================
# DETERMINISTIC SCORING NODE (non-LLM)
# ===================================================================

def scoring_node(state: Dict[str, Any]) -> Dict[str, Any]:
    pq = state.get("parsed_query", {})
    direction = pq.get("direction", "over")
    scorecard = compute_scorecard(
        historical_signals=state.get("historical_signals", {}),
        projection_signals=state.get("projection_signals", {}),
        market_signals=state.get("market_signals", {}),
        direction=direction,
    )
    return {
        "scorecard": scorecard,
        "data_quality_flags": scorecard.get("data_quality_flags", []),
        "audit_log": state.get("audit_log", []) + [{"node": "scoring", "scorecard": scorecard}],
    }


# ===================================================================
# 5. CRITIC
# ===================================================================

_CRITIC_SYSTEM = """\
You are the Critic of an NBA player-prop betting advisor.

You receive a deterministic scorecard and dimension signals. Your job is to
ATTACK the scorecard — find weaknesses, contradictions, and risks.

IMPORTANT – Direction context:
- The scorecard includes a "direction" field ("over" or "under") indicating which
  side the user is asking about.
- model_probability and market_implied_probability are ALREADY adjusted for that
  direction. For example, if direction="under", model_probability = P(under).
- hit_rate and shrunk_rate in raw signal details are ALWAYS P(over > threshold).
  When direction="under", the relevant probability is 1 - hit_rate.

Required checks:
- Double-counting risk across trend / shooting / recent form
- Small or asymmetric samples
- Stale roster assumptions
- OWN-TEAM INJURY REPORT: Are key teammates OUT or QUESTIONABLE? If so,
  what is the chemistry_delta for each one (positive = player does better WITH
  the star, so losing them HURTS)? Has the scorecard adequately accounted for
  the combined impact of multiple missing teammates?
- Opponent injury report: Does the opponent being weakened or strong affect
  game script and therefore player opportunity?
- High variance with weak payout edge
- Market disagreement or line movement against the recommendation
- Whether the deterministic score is overconfident relative to signal quality

Output ONLY a JSON object:
{
  "risk_factors": ["..."],
  "risk_grade": "low | medium | high",
  "reasoning": "..."
}
"""


def critic_node(state: Dict[str, Any]) -> Dict[str, Any]:
    scorecard = state.get("scorecard", {})
    hist = state.get("historical_signals", {})
    market = state.get("market_signals", {})
    flags = state.get("data_quality_flags", [])

    tm_details = hist.get("auto_teammate_impact", {}).get("details") or {}
    own_inj = hist.get("get_own_team_injury_report", {}).get("details") or {}

    summary = json.dumps({
        "scorecard": scorecard,
        "data_quality_flags": flags,
        "base_stats_signal": hist.get("get_base_stats", {}).get("signal"),
        "base_stats_n": hist.get("get_base_stats", {}).get("sample_size"),
        "trend_signal": hist.get("get_trend_analysis", {}).get("signal"),
        "variance_cv": (hist.get("get_variance_profile", {}).get("details") or {}).get("cv"),
        "market_signal": market.get("get_current_market", {}).get("signal"),
        "teammate_scenario": tm_details.get("today_scenario"),
        "teammate_chemistry_details": tm_details.get("teammate_chemistry", []),
        "own_team_injury_report": own_inj.get("injuries", []),
    }, indent=2, default=str)

    resp = _get_llm().invoke([
        SystemMessage(content=_CRITIC_SYSTEM),
        HumanMessage(content=summary),
    ])
    text = resp.content.strip()

    try:
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        critic = json.loads(text)
    except json.JSONDecodeError:
        critic = {"risk_factors": [text], "risk_grade": "medium", "reasoning": text}

    notes = critic.get("risk_factors", [])

    return {
        "critic_notes": notes,
        "audit_log": state.get("audit_log", []) + [{"node": "critic", "output": critic}],
    }


# ===================================================================
# 6. SYNTHESIZER
# ===================================================================

_SYNTH_SYSTEM = """\
You are the Synthesizer of an NBA player-prop betting advisor.

You receive:
- The deterministic scorecard (the authoritative decision source)
- Dimension signals
- Critic risk notes

IMPORTANT – Direction context:
- The scorecard includes a "direction" field ("over" or "under") indicating which
  side the user is asking about.
- model_probability and market_implied_probability are ALREADY adjusted for that
  direction. For example, if direction="under", model_probability = P(under),
  market_implied_probability = P(under), and expected_value_pct is for the under side.
- hit_rate and shrunk_rate in raw signal details are ALWAYS P(over > threshold).
  When direction="under", the relevant probability is 1 - hit_rate.
- When explaining to the user, always tie model_probability and EV to the user's
  bet direction. E.g. "Model estimates a 66.5% probability of going UNDER."

Your job: EXPLAIN the scorecard to the user. Do NOT override the decision.
Critic notes are risk context only. They can change the framing of the summary,
but they must NOT change the final decision.

Output ONLY a JSON object:
{
  "decision": "over | under | avoid",
  "confidence": <float 0-1>,
  "model_probability": <float>,
  "market_implied_probability": <float or null>,
  "expected_value_pct": <float>,
  "dimensions": {
    "historical": {"signal": "...", "reliability": <float>, "detail": "..."},
    "trend_role": {"signal": "...", "reliability": <float>, "detail": "..."},
    "shooting": {"signal": "...", "reliability": <float>, "detail": "..."},
    "variance": {"signal": "...", "reliability": <float>, "detail": "..."},
    "schedule": {"signal": "...", "reliability": <float>, "detail": "..."},
    "own_team_injuries": {"signal": "...", "reliability": <float>,
      "detail": "list OUT/QUE teammates and chemistry_delta impact on target player"},
    "projection": {"signal": "unavailable", "reliability": 0.0, "detail": "dummy data excluded"},
    "market": {"signal": "...", "reliability": <float>, "detail": "..."}
  },
  "risk_factors": ["..."],
  "summary": "one paragraph conclusion – MUST mention own-team injury impacts if any key teammates are OUT/Questionable, and always specify whether the probability/EV is for over or under",
  "needs_retry": false,
  "retry_reason": null
}

Set needs_retry=true ONLY if mandatory market data or injury context is completely missing.
Do NOT retry just because you feel uncertain.
"""


def synthesizer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    scorecard = state.get("scorecard", {})
    hist = state.get("historical_signals", {})
    market = state.get("market_signals", {})
    proj = state.get("projection_signals", {})
    critic_notes = state.get("critic_notes", [])

    payload = json.dumps({
        "scorecard": scorecard,
        "critic_notes": critic_notes,
        "historical_base": hist.get("get_base_stats", {}),
        "trend": hist.get("get_trend_analysis", {}),
        "shooting": hist.get("get_shooting_profile", {}),
        "variance": hist.get("get_variance_profile", {}),
        "schedule": hist.get("get_schedule_context", {}),
        "teammate_chemistry": hist.get("auto_teammate_impact", {}),
        "own_team_injury_report": hist.get("get_own_team_injury_report", {}),
        "opponent_injury_report": hist.get("get_opponent_injury_report", {}),
        "market_current": market.get("get_current_market", {}),
        "market_query_quote": market.get("get_market_quote_for_line", {}),
        "projection_status": "all_unavailable",
    }, indent=2, default=str)

    resp = _get_llm().invoke([
        SystemMessage(content=_SYNTH_SYSTEM),
        HumanMessage(content=payload),
    ])
    text = resp.content.strip()

    try:
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        final = json.loads(text)
    except json.JSONDecodeError:
        final = {
            "decision": scorecard.get("decision", "avoid"),
            "confidence": scorecard.get("confidence", 0),
            "model_probability": scorecard.get("model_probability", 0),
            "market_implied_probability": scorecard.get("market_implied_probability"),
            "expected_value_pct": scorecard.get("expected_value_pct", 0),
            "dimensions": {},
            "risk_factors": critic_notes,
            "summary": text,
            "needs_retry": False,
            "retry_reason": None,
        }

    # Deterministic scoring is authoritative; the synthesizer only explains it.
    final["decision"] = scorecard.get("decision", final.get("decision", "avoid"))

    needs_retry = final.get("needs_retry", False)
    iteration = state.get("iteration", 0)
    if iteration >= 2:
        needs_retry = False

    return {
        "final_decision": final,
        "iteration": iteration + 1,
        "audit_log": state.get("audit_log", []) + [{"node": "synthesizer", "decision": final.get("decision")}],
    }
