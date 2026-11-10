# SPO-107 — Match the walk-forward harness to production game types

- **Ticket:** SPO-107
- **Branch:** `feature/SPO-107-harness-gametype-parity`
- **Base:** `dev`

## Summary

The walk-forward harness was still keeping playoffs and the play-in in both history and the headline targets. Production, since SPO-97, uses regular-season games only (`CSVPlayerHistoryService._allowed_game_types`). Headline history and headline targets now call that method. Playoffs and the play-in are scored with the same regular-season history and reported in their own section. The CI guard compares 25 daily L10 rates per league with `get_player_stats` and fails on any mismatch. `backtest_report.md` and the pinned headlines in `oracle.py` are the full run on the post-SPO-97 CSVs. `--check-oracle` passes. The full run checked 150 rows per league against `get_player_stats` with 0 mismatches.

## Changes

| File | Change |
|---|---|
| `scripts/agents/evaluation/walk_forward.py` | `_active_games` keeps production's regular-season set. Playoff and play-in targets go to separate lists. |
| `scripts/agents/evaluation/report.py` | Headline text is regular season. New "Playoffs and play-in" section. |
| `scripts/agents/evaluation/calibration_guard.py` | CI sample compares 25 L10 rows per league (seed 7) with `get_player_stats`. A mismatch fails. |
| `scripts/agents/evaluation/oracle.py` | Pinned headlines replaced with this run. |
| `scripts/agents/evaluation/backtest.py` | Success note states the regular-season window, the proxy line, and -110. |
| `backtest_report.md` | Regenerated from the full run. |
| `scripts/agents/tests/test_spo107_harness_gametype.py` | History matches production. A playoff game is not a headline target. |
| `scripts/agents/tests/test_calibration_guard.py` | A production-rate mismatch fails the guard. |
| `scripts/agents/tests/test_spo99_critical_paths.py` | Real-CSV prior counts regular-season games. |
| `.github/workflows/ci.yml` | Walk-forward job runs the SPO-107 tests. |
| `docs/progress.md` | SPO-107 under In flight. |
| `docs/decisions/SPO-107/decision_20261110_regular-season-harness.md` | Why the harness uses the production game-type set. |

## Why

A prior window that still contained a playoff game did not match `get_player_stats`, which drops that game. On this CSV that was 12 of 150 NBA rows and 11 of 150 WNBA rows. The guard had `validate=0`, so CI never saw it. Filtering history to the production set makes that comparison match (0 of 150).

Leaving playoff targets inside the headline would still mix a postseason game into the number this report compares with the regular-season product. Dropping them from the report would hide a question the file can answer. They are scored with regular-season history, which is what production would have used that morning, and printed apart from the headlines.

The Cup final stays out of both lists. `_allowed_game_types` does not include it even when playoffs and the play-in are opted in.

Copying the token `regular_season` into the harness was rejected. The harness calls `_allowed_game_types()` and `_game_type_of`, so a new opt-in on the service reaches the replay. A missing `game_type` still counts as regular season.

A playoff game's prior does not include earlier playoff games. That matches the production default. It is not a series-form backtest.

## Tests / Verification

- `python3 -m pytest scripts/agents/tests/test_spo99_critical_paths.py scripts/agents/tests/test_spo107_harness_gametype.py scripts/agents/tests/test_walk_forward_backtest.py scripts/agents/tests/test_calibration_guard.py -q` — 47 passed, about 4s. The guard sample is 40 players per league, seed 7, plus 25 production-rate rows per league.
- `python3 scripts/agents/evaluation/backtest.py --report backtest_report.md --check-oracle` — exit 0. 150/150 NBA and 150/150 WNBA rates matched `get_player_stats`. Elapsed about 76s.
- `ruff==0.17.4 check backend --select E9,F63,F7,F82` — passed. `python3 -m compileall -q backend` — passed.
- Integration test: SKIPPED (no live API in this change).
- Fabrication scan (Mock without fixture): PASS. No new external API client.

## Follow-ups

- A series-form backtest would pass `include_playoffs=True` into the prior window. This report does not.
- WNBA has no play-in rows in the current file, so that breakdown row is absent.
