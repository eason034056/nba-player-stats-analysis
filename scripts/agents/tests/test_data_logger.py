"""SPO-70 — unit tests for scripts/agents/data_logger.py.

`data_logger.py` powers the ``cli.py --log-data`` debug path: it formats the
full LangGraph ``state`` (parsed query + every product agent's signals) to
stdout so a developer can see exactly what each agent fetched and why a pick
was made. If it crashes on a partial or malformed ``state`` the trace dies at
the exact moment it is most needed, so this is a zero-production-risk lockdown
of a debug-critical module (same shape as the SPO-67 date_utils tests).

Strategy:
  * Drive the public entry point ``log_all_agent_data`` and assert on captured
    stdout via pytest's ``capsys`` — that is the module's only real contract.
  * Unit-test the two private helpers (``_format_signal``, ``_log_signal_group``)
    directly since they return strings and own the robustness guards.
  * Use stable, structural assertions (substring / "not in") rather than exact
    full-output matches, so cosmetic banner tweaks don't make the suite brittle.

These tests assert behaviour/output only; they do not refactor the SUT.
"""

import data_logger
from data_logger import (
    TOOL_EXPLANATIONS,
    _format_signal,
    _log_signal_group,
    log_all_agent_data,
)


# ---------------------------------------------------------------------------
# Fixtures / sample builders
# ---------------------------------------------------------------------------

def _sample_signal() -> dict:
    """A representative signal dict shaped like a real historical/market signal."""
    return {
        "signal": "base_points_hit_rate",
        "effect_size": 0.62,
        "sample_size": 40,
        "reliability": 0.8,
        "window": "season",
        "source": "nba_player_game_logs.csv",
        "as_of": "2026-05-29",
        "details": {"mean": 24.1, "hit_rate": 0.62},
    }


# ---------------------------------------------------------------------------
# Criterion 1 — empty state is safe and still prints the banner
# ---------------------------------------------------------------------------

def test_log_all_agent_data_empty_state_prints_banner_no_raise(capsys):
    log_all_agent_data({})  # must not raise on a completely empty state
    out = capsys.readouterr().out
    assert "AGENT 抓取資料總覽" in out  # header banner always prints
    # None of the optional sections should appear for an empty state.
    assert "Planner 解析結果" not in out
    assert "Historical Agent" not in out
    assert "Query-Aligned Context" not in out


# ---------------------------------------------------------------------------
# Criterion 2 — partial state prints only the present section
# ---------------------------------------------------------------------------

def test_log_all_agent_data_only_parsed_query_prints_planner_skips_rest(capsys):
    state = {
        "parsed_query": {
            "player": "Anthony Edwards",
            "metric": "points",
            "threshold": 24.5,
            "date": "2026-05-29",
            "opponent": "LAL",
            "direction": "over",
        }
    }
    log_all_agent_data(state)
    out = capsys.readouterr().out

    assert "Planner 解析結果" in out
    assert "Anthony Edwards" in out
    assert "24.5" in out
    # Signal groups absent because their state keys are missing.
    assert "Historical Agent" not in out
    assert "Market Agent" not in out
    assert "Projection Agent" not in out


# ---------------------------------------------------------------------------
# Criterion 3 — _log_signal_group skips non-dict signal values (isinstance guard)
# ---------------------------------------------------------------------------

def test_log_signal_group_skips_non_dict_value_without_crashing():
    # A malformed group where a tool key maps to None instead of a dict.
    result = _log_signal_group(
        {"get_base_stats": None}, "Malformed Group", TOOL_EXPLANATIONS
    )
    assert "Malformed Group" in result  # group header still rendered
    # The None entry is skipped by the `isinstance(data, dict)` guard, so no
    # per-signal body (▶ / signal:) is emitted for it.
    assert "▶" not in result
    assert "signal:" not in result


def test_log_signal_group_renders_dict_value():
    # Sanity counterpart: a valid dict value IS rendered with header + body.
    result = _log_signal_group(
        {"get_base_stats": _sample_signal()}, "Historical", TOOL_EXPLANATIONS
    )
    assert "▶" in result
    assert "說明" in result
    assert "資料來源" in result
    assert "base_points_hit_rate" in result  # from _format_signal


# ---------------------------------------------------------------------------
# Criterion 4 — _format_signal happy-path output
# ---------------------------------------------------------------------------

def test_format_signal_happy_path_emits_all_fields():
    out = _format_signal(_sample_signal())
    assert "signal: base_points_hit_rate" in out
    assert "effect_size: 0.62" in out
    assert "sample_size: 40" in out
    assert "reliability: 0.8" in out
    assert "window: season" in out
    assert "source: nba_player_game_logs.csv" in out
    assert "as_of: 2026-05-29" in out
    # details present → serialized as JSON
    assert "details:" in out
    assert "24.1" in out


def test_format_signal_missing_fields_use_defaults():
    # Empty signal must not raise; falls back to the "?"/0 placeholders.
    out = _format_signal({})
    assert "signal: ?" in out
    assert "effect_size: 0" in out
    assert "details:" not in out  # no details key → no details line


def test_log_signal_group_header_and_explanation_lines():
    # NOTE: the ▶ / 說明 / 資料來源 lines referenced in the ticket are emitted by
    # _log_signal_group (which wraps _format_signal), so the happy-path
    # explanation rendering is asserted here against a known TOOL_EXPLANATIONS key.
    result = _log_signal_group(
        {"get_current_market": _sample_signal()}, "Market", TOOL_EXPLANATIONS
    )
    exp = TOOL_EXPLANATIONS["get_current_market"]
    assert f"▶ {exp['name']}" in result
    assert exp["source"] in result


# ---------------------------------------------------------------------------
# Criterion 5a — market exact_line / available_lines note branch
# ---------------------------------------------------------------------------

def _market_state(pricing_mode: str, available_lines: list) -> dict:
    quote = _sample_signal()
    quote["details"] = {
        "pricing_mode": pricing_mode,
        "available_lines": available_lines,
    }
    return {"market_signals": {"get_market_quote_for_line": quote}}


def test_market_note_warns_when_line_not_exact(capsys):
    log_all_agent_data(_market_state("nearest_line", [23.5, 24.5]))
    out = capsys.readouterr().out
    assert "Market Note" in out
    # non-exact pricing → warning + the available lines are listed
    assert "查詢線沒有精準對上" in out
    assert "23.5" in out
    assert "24.5" in out


def test_market_note_skips_warning_when_exact_line(capsys):
    log_all_agent_data(_market_state("exact_line", [24.5]))
    out = capsys.readouterr().out
    assert "Market Note" in out  # note block still prints
    # exact_line short-circuits the mismatch warning branch
    assert "查詢線沒有精準對上" not in out


# ---------------------------------------------------------------------------
# Criterion 5b — query_aligned_context query_probability formatting branch
# ---------------------------------------------------------------------------

def test_query_aligned_context_formats_probabilities_when_present(capsys):
    state = {
        "scorecard": {
            "query_aligned_context": {
                "query_side": "over",
                "historical": {"query_probability": 0.5823},
                "market": {"query_probability": 0.55},
            }
        }
    }
    log_all_agent_data(state)
    out = capsys.readouterr().out
    assert "Query-Aligned Context" in out
    assert "query_side: over" in out
    # floats are rendered with .4f formatting
    assert "0.5823" in out
    assert "0.5500" in out


def test_query_aligned_context_skips_probability_lines_when_absent(capsys):
    state = {
        "scorecard": {
            "query_aligned_context": {
                "query_side": "under",
                "historical": {},  # no query_probability key
                "market": {},
            }
        }
    }
    log_all_agent_data(state)
    out = capsys.readouterr().out
    assert "Query-Aligned Context" in out
    assert "query_side: under" in out
    # query_probability is None/absent → the formatted lines are silently skipped
    assert "query_probability:" not in out


def test_scorecard_non_dict_does_not_crash(capsys):
    # Defensive: scorecard present but not a dict → query_ctx falls back to {}.
    log_all_agent_data({"scorecard": "unexpected"})
    out = capsys.readouterr().out
    assert "Query-Aligned Context" not in out  # nothing to render, no crash


# ---------------------------------------------------------------------------
# data_quality_flags rendering (extra coverage, same entry point)
# ---------------------------------------------------------------------------

def test_data_quality_flags_are_listed(capsys):
    log_all_agent_data({"data_quality_flags": ["small_sample", "stale_line"]})
    out = capsys.readouterr().out
    assert "資料品質旗標" in out
    assert "small_sample" in out
    assert "stale_line" in out


def test_module_exposes_expected_public_surface():
    # Guards against accidental rename of the helpers these tests target.
    assert callable(data_logger.log_all_agent_data)
    assert callable(data_logger._format_signal)
    assert callable(data_logger._log_signal_group)
