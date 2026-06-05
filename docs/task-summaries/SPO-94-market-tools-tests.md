# SPO-94 — Unit tests for tools/market.py (zero-coverage pricing tool layer)

## Summary

Adds `scripts/agents/tests/test_tools_market.py` (169 lines, 14 tests) covering the
deterministic helpers in the agent pricing tool layer. This continues the
"zero-coverage critical path" test pattern from SPO-67/70/73/76.

## Changes

| File | Action | LOC delta |
|------|--------|-----------|
| `scripts/agents/tests/test_tools_market.py` | New | +169 |

No production files were modified.

## Why

`scripts/agents/tools/market.py` (579 LOC) was the last zero-coverage file in the
deterministic helper layer. These helpers convert raw bookmaker odds into fair
probability and signal payloads consumed by the scoring node — untested bugs here
silently corrupt every downstream betting recommendation.

## Tests added

| Test | Helper | Assertion |
|------|--------|-----------|
| `test_sport_key_routes_nba_and_wnba` | `_sport_key_for` | NBA and WNBA produce correct sport keys |
| `test_sport_key_is_case_insensitive` | `_sport_key_for` | Uppercase input normalized correctly |
| `test_sport_key_defaults_to_nba_on_empty_or_unknown` | `_sport_key_for` | Empty / None / unknown → `basketball_nba` |
| `test_market_map_has_expected_keys_and_values` | `MARKET_MAP` | Exact key/value table verified |
| `test_normalize_direction_passes_through_concrete_side` | `_normalize_direction` | `"over"` / `"UNDER"` returned lowercased |
| `test_normalize_direction_resolves_any_to_majority_side` | `_normalize_direction` | `"any"` → over or under per consensus fair_over |
| `test_normalize_direction_any_with_no_lines_defaults_over` | `_normalize_direction` | Empty lines → `"over"` (mean=0.5 threshold) |
| `test_same_line_lines_groups_only_matching_line_within_tolerance` | `_same_line_lines` | Float-tolerant line grouping |
| `test_same_line_side_prob_averages_correct_side` | `_same_line_side_prob` | Mean fair_over / fair_under for matched books |
| `test_same_line_side_prob_returns_none_on_empty` | `_same_line_side_prob` | Empty list → `None` |
| `test_signal_payload_rounds_effect_and_clamps_reliability` | `_signal_payload` | 4dp rounding + reliability clamped to [0,1] |
| `test_build_quote_unavailable_when_threshold_non_positive` | `_build_market_quote_for_line` | `threshold=0` → `unavailable` mode |
| `test_build_quote_exact_line_picks_best_over_price` | `_build_market_quote_for_line` | `exact_line` mode, correct best-book selection |
| `test_build_quote_line_moved_falls_back_to_nearest_line` | `_build_market_quote_for_line` | `line_moved` mode with nearest-line fallback |

## Follow-ups

None — integration tests for the async `_fetch_market_data` / `get_*` public tools
are gated behind `RUN_INTEGRATION=1` per the existing project pattern.
