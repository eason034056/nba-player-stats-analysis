"""SPO-94 — unit tests for the deterministic helpers in
`scripts/agents/tools/market.py` (the agent pricing tool layer).

Scope (per ticket): only the pure / synchronous helpers that need no
network. The `async def` functions that hit The Odds API (`_get_events`,
`_get_player_odds`, `_fetch_market_data`, and the public `get_*` tools)
are deliberately NOT exercised here — they are covered by the integration
patterns gated behind RUN_INTEGRATION elsewhere.

Helpers under test:
  - `_sport_key_for`            league → sport_key routing
  - `MARKET_MAP`               metric → Odds-API market-key table
  - `_normalize_direction`     resolve 'any' into a concrete side
  - `_same_line_lines`         float-tolerant line grouping
  - `_same_line_side_prob`     side probability extraction
  - `_signal_payload`          payload assembly (rounding / clamping)
  - `_build_market_quote_for_line`  exact-line / line-moved / unavailable
"""

import tools.market as market


def _line(bookmaker, line, over_odds, under_odds, fair_over, fair_under):
    """Build one bookmaker line row in the shape `_extract_player_lines` emits."""
    return {
        "bookmaker": bookmaker,
        "line": float(line),
        "over_odds": int(over_odds),
        "under_odds": int(under_odds),
        "vig": 0.04,
        "fair_over": fair_over,
        "fair_under": fair_under,
    }


# ---------------------------------------------------------------------------
# _sport_key_for  +  MARKET_MAP
# ---------------------------------------------------------------------------

def test_sport_key_routes_nba_and_wnba():
    assert market._sport_key_for("nba") == "basketball_nba"
    assert market._sport_key_for("wnba") == "basketball_wnba"


def test_sport_key_is_case_insensitive():
    assert market._sport_key_for("WNBA") == "basketball_wnba"
    assert market._sport_key_for("Nba") == "basketball_nba"


def test_sport_key_defaults_to_nba_on_empty_or_unknown():
    # Empty / None / garbage all fall back to the legacy NBA sport_key.
    assert market._sport_key_for("") == "basketball_nba"
    assert market._sport_key_for(None) == "basketball_nba"
    assert market._sport_key_for("cricket") == "basketball_nba"


def test_market_map_has_expected_keys_and_values():
    assert market.MARKET_MAP == {
        "points": "player_points",
        "rebounds": "player_rebounds",
        "assists": "player_assists",
        "pra": "player_points_rebounds_assists",
    }


# ---------------------------------------------------------------------------
# _normalize_direction
# ---------------------------------------------------------------------------

def test_normalize_direction_passes_through_concrete_side():
    # A concrete direction is returned lowercased and never consults `lines`.
    assert market._normalize_direction("over", []) == "over"
    assert market._normalize_direction("UNDER", []) == "under"


def test_normalize_direction_resolves_any_to_majority_side():
    over_lean = [_line("dk", 25.5, -110, -110, 0.62, 0.38)]
    under_lean = [_line("dk", 25.5, -110, -110, 0.40, 0.60)]
    assert market._normalize_direction("any", over_lean) == "over"
    assert market._normalize_direction("any", under_lean) == "under"


def test_normalize_direction_any_with_no_lines_defaults_over():
    # mean of [] -> 0.5 consensus, and 0.5 >= 0.5 resolves to "over".
    assert market._normalize_direction("any", []) == "over"


# ---------------------------------------------------------------------------
# _same_line_lines  +  _same_line_side_prob
# ---------------------------------------------------------------------------

def test_same_line_lines_groups_only_matching_line_within_tolerance():
    lines = [
        _line("dk", 25.5, -110, -110, 0.5, 0.5),
        _line("fd", 25.5, -115, -105, 0.5, 0.5),
        _line("mgm", 26.5, -110, -110, 0.5, 0.5),
    ]
    # An int threshold of 25.5 still matches the float-stored 25.5 rows.
    matched = market._same_line_lines(lines, 25.5)
    assert {m["bookmaker"] for m in matched} == {"dk", "fd"}


def test_same_line_side_prob_averages_correct_side():
    lines = [
        _line("dk", 25.5, -110, -110, 0.60, 0.40),
        _line("fd", 25.5, -110, -110, 0.50, 0.50),
    ]
    assert market._same_line_side_prob(lines, "over") == 0.55
    assert market._same_line_side_prob(lines, "under") == 0.45


def test_same_line_side_prob_returns_none_on_empty():
    assert market._same_line_side_prob([], "over") is None


# ---------------------------------------------------------------------------
# _signal_payload
# ---------------------------------------------------------------------------

def test_signal_payload_rounds_effect_and_clamps_reliability():
    payload = market._signal_payload(
        "neutral", 0.123456, 4, 1.7, "today", "odds_api", {"k": "v"}
    )
    assert payload["signal"] == "neutral"
    assert payload["effect_size"] == 0.1235          # rounded to 4dp
    assert payload["reliability"] == 1.0             # clamped into [0, 1]
    assert payload["sample_size"] == 4
    assert payload["details"] == {"k": "v"}
    assert "as_of" in payload                        # timestamp always stamped


# ---------------------------------------------------------------------------
# _build_market_quote_for_line  (three pricing modes)
# ---------------------------------------------------------------------------

def test_build_quote_unavailable_when_threshold_non_positive():
    lines = [_line("dk", 25.5, -110, -110, 0.5, 0.5)]
    result = market._build_market_quote_for_line(lines, 0, "over")
    assert result["signal"] == "unavailable"
    assert result["details"]["pricing_mode"] == "unavailable"


def test_build_quote_exact_line_picks_best_over_price():
    lines = [
        _line("dk", 25.5, -120, -110, 0.58, 0.42),
        _line("fd", 25.5, -105, -115, 0.56, 0.44),   # best over price (least negative)
    ]
    result = market._build_market_quote_for_line(lines, 25.5, "over")
    assert result["signal"] == "neutral"
    assert result["details"]["pricing_mode"] == "exact_line"
    assert result["details"]["matched_n_books"] == 2
    assert result["details"]["best_book"] == "fd"
    assert result["details"]["best_odds"] == -105
    # market_implied_for_query == mean fair_over of the matched books.
    assert result["details"]["market_implied_for_query"] == 0.57


def test_build_quote_line_moved_falls_back_to_nearest_line():
    lines = [
        _line("dk", 24.5, -110, -110, 0.5, 0.5),
        _line("fd", 26.5, -110, -110, 0.5, 0.5),
    ]
    # 25.5 is unavailable; nearest by (abs distance, line) is 24.5.
    result = market._build_market_quote_for_line(lines, 25.5, "over")
    assert result["signal"] == "caution"
    assert result["details"]["pricing_mode"] == "line_moved"
    assert result["details"]["best_line"] == 24.5
    assert result["details"]["queried_line"] == 25.5
    assert result["details"]["available_lines"] == [24.5, 26.5]
