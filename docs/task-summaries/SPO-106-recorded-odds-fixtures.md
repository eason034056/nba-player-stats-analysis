# SPO-106 — Recorded Odds API fixtures

- Ticket: SPO-106
- Branch: `feature/SPO-106-recorded-odds-fixtures` (from `origin/dev` at `53fe0c4`)

## Summary

Unit tests that only need a shape the SPO-98 capture already has now load that capture through `tests.fixtures.odds_api.load_odds_fixture`. A smaller case is a named copy of that body (one bookmaker, one side removed, a player and line rewritten). Markets the capture does not contain stay on their inline builders, each marked `TODO(SPO-106)`, and switch to the recording when the file from `record_fixtures.py` posts an outcome.

`record_fixtures.py` was not run. `ODDS_API_KEY` was not available, so no body was invented and no Odds API credit was spent.

Live WNBA tests for rebounds, assists, threes, and the four combo markets are gated on `RUN_INTEGRATION=1` and were not executed.

## What is already recorded

| File | League | Markets |
|---|---|---|
| `backend/tests/fixtures/odds_api_events__basketball_nba.json` | `basketball_nba` | none (events list) |
| `backend/tests/fixtures/odds_api_event_odds__player_points.json` | `basketball_nba` (Lakers @ Hawks, `07361a8381206817e27bd2697fad7479`) | `player_points` only, 6 bookmakers |

No WNBA body is on disk. No file contains rebounds, assists, threes, steals, free throws, field goals, a combo market, or double-double.

## Hand-typed bodies

| Site | Result |
|---|---|
| `test_odds_gateway.py` `_sample_payload` | Replaced. FanDuel's first recorded Over/Under pair. Stale-refresh cases relabel `description` and `point` (`old value` / `fresh value`). |
| `test_odds_snapshot.py` `_make_event` | Replaced. First recorded NBA event, with id, teams, and `commence_time` overridden for the date filter. |
| `test_odds_snapshot.py` player_points rows | Replaced. DraftKings and FanDuel sliced to Luka Doncic and Jalen Johnson. Missing Under, zero price, null line, and empty books are copies of that slice. |
| `test_odds_snapshot.py` `test_process_event_missing_over` | Waiting. Inline `player_rebounds` Under-only builder until `odds_api_event_odds__nba_expanded_markets.json` posts `player_rebounds`. |
| `test_spo16_market_expansion.py` `_dd_market_payload` | Waiting. Yes-only, Yes+No, and No-only stay inline until the expanded file posts `player_double_double` with that side. |
| `test_daily_analysis.py` `_make_bookmakers_data` and the group-props boards | Replaced. Recorded bookmaker shell; player names and lines are the test's controls. |
| `test_daily_analysis_league.py` `_bookmakers_for` | Waiting. Inline builder until `odds_api_event_odds__wnba_expanded_markets.json` exists. |
| `test_spo98_team_and_names.py` | Replaced. Same two files, now via `load_odds_fixture`. |

## Changes

| Area | File | Change |
|---|---|---|
| Loader | `backend/tests/fixtures/odds_api/__init__.py` | `load_odds_fixture`, `derive_line_board`, `first_posted_market`. |
| Recorder | `backend/tests/fixtures/odds_api/record_fixtures.py` | One NBA odds call for the unrecorded markets. WNBA odds call only if an event is listed. Prints `x-requests-used`, `x-requests-remaining`, `x-requests-last`. Saves raw bytes and strips the key. |
| Gateway tests | `backend/tests/test_odds_gateway.py` | Payloads come from the player_points capture. |
| Snapshot tests | `backend/tests/test_odds_snapshot.py` | Events and player_points rows come from the captures. Rebounds Under-only still inline. |
| DD tests | `backend/tests/test_spo16_market_expansion.py` | Switch onto a recorded DD market when one exists. |
| Daily picks tests | `backend/tests/test_daily_analysis.py` | Bookmaker boards are derived from player_points. |
| WNBA routing test | `backend/tests/test_daily_analysis_league.py` | Switches when a WNBA odds file exists. |
| SPO-98 wiring | `backend/tests/test_spo98_team_and_names.py` | Uses the shared loader. |
| Inventory | `backend/tests/test_spo106_recorded_fixtures.py` | Asserts the two files, and that the expanded files are absent. |
| WNBA live | `backend/tests/test_spo106_wnba_live_markets.py` | One batched odds call. Skipped unless `RUN_INTEGRATION=1`. Empty bookmakers yield an empty board. |
| Docs | `docs/progress.md`, `backend/tests/fixtures/README.md` | SPO-106 row. Recorder contract. |

## Why

A hand-typed bookmaker dict proves the code runs against a shape somebody remembered. The SPO-98 capture is a real `player_points` body, so every test that only needs that shape should start there. Relabeling a player or deleting Under is a derivation of that body. It is not a new response.

The other markets are a different response. Writing them from memory would be the failure this ticket exists to stop. The inline builders stay, with an explicit switch, until `record_fixtures.py` has been run once. That script makes one paid NBA call (every missing market in one `markets=` parameter, DraftKings and FanDuel only) and a WNBA call only when the free events list is non-empty. The events list is not written over the SPO-98 file.

The WNBA live tests follow the same batching idea: one events call, one odds call, then `american_to_prob` and `devig` — the functions `nba.py` and `wnba.py` use. A market that is not posted produces no row. Those tests are not part of the default run.

## Tests

```
cd backend && pytest -q
cd scripts/agents && pytest -q
```

`RUN_INTEGRATION` was unset. The live WNBA class did not call The Odds API.

Recorder: not run. No key.

## Follow-ups

- Run `backend/tests/fixtures/odds_api/record_fixtures.py` once `ODDS_API_KEY` is available. Commit the raw bodies. The tests named "Waiting" above pick the recording up when the market is actually in the file.
- `test_spo106_recorded_fixtures.py` asserts the expanded files are absent. That assertion is the checklist item to update in the same commit as the bodies.
- The group-props and daily-picks tests still rewrite player names and lines. Those values are the cases under test (threshold, consensus, team). The bookmaker shell is the recorded one.
