# SPO-106 — Recorded NBA Odds API fixtures

- Ticket: SPO-106
- Branch: `feature/SPO-106-recorded-odds-fixtures` (from `origin/dev`, merged through `63d309e`)

## Summary

This pull request is NBA only. WNBA fixture work is deferred while WNBA work is paused.

Unit tests that only need a shape a recorded capture already has load that capture through `tests.fixtures.odds_api.load_odds_fixture`. A smaller case is a named copy of that body (one bookmaker, one side removed, a player and line rewritten). A side the expanded capture did not post stays on its inline builder, marked `TODO(SPO-106)`.

The expanded body was recorded 2026-11-10T19:02:40Z and committed unchanged, with `odds_api_event_odds__nba_expanded_markets.meta.json` beside it. This branch did not call The Odds API.

## What is already recorded

| File | League | Markets |
|---|---|---|
| `backend/tests/fixtures/odds_api_events__basketball_nba.json` | `basketball_nba` | none (events list) |
| `backend/tests/fixtures/odds_api_event_odds__player_points.json` | `basketball_nba` (Lakers @ Hawks, `07361a8381206817e27bd2697fad7479`) | `player_points` only, 6 bookmakers |
| `backend/tests/fixtures/odds_api_event_odds__nba_expanded_markets.json` | `basketball_nba` (Celtics @ 76ers, `cfa503c66cd505776a910921875ef7dd`, `2026-11-11T01:10:00Z`) | FanDuel and DraftKings: assists, rebounds, threes, steals, the four combo markets, double-double Yes. Not posted: `player_frees_made`, `player_field_goals`, double-double No. |

## Hand-typed bodies

| Site | Result |
|---|---|
| `test_odds_gateway.py` `_sample_payload` | Replaced. FanDuel's first recorded Over/Under pair. Stale-refresh cases relabel `description` and `point` (`old value` / `fresh value`). |
| `test_odds_snapshot.py` `_make_event` | Replaced. First recorded NBA event, with id, teams, and `commence_time` overridden for the date filter. |
| `test_odds_snapshot.py` player_points rows | Replaced. DraftKings and FanDuel sliced to Luka Doncic and Jalen Johnson. Missing Under, zero price, null line, and empty books are copies of that slice. |
| `test_odds_snapshot.py` `test_process_event_missing_over` | Switched. Recorded FanDuel `player_rebounds`, Over removed. |
| `test_spo16_market_expansion.py` Yes-only | Switched. First recorded Yes (FanDuel, Joel Embiid, 142). |
| `test_spo16_market_expansion.py` Yes+No and No-only | Still inline. The recording has no No, so those prices were not invented. `TODO(SPO-106)` stays on that builder. |
| `test_daily_analysis.py` `_make_bookmakers_data` and the group-props boards | Replaced. Recorded bookmaker shell; player names and lines are the test's controls. |
| `test_spo98_team_and_names.py` | Replaced. Same two files, now via `load_odds_fixture`. |

## Changes

| Area | File | Change |
|---|---|---|
| Loader | `backend/tests/fixtures/odds_api/__init__.py` | `load_odds_fixture`, `derive_line_board`, `first_posted_market`. |
| Recorder | `backend/tests/fixtures/odds_api/record_fixtures.py` | Free NBA events call, then one NBA odds call for the unrecorded markets. Prints `x-requests-used`, `x-requests-remaining`, `x-requests-last`. Saves raw bytes and strips the key. |
| Gateway tests | `backend/tests/test_odds_gateway.py` | Payloads come from the player_points capture. |
| Snapshot tests | `backend/tests/test_odds_snapshot.py` | Events and player_points rows come from the captures. Rebounds Under-only drops Over from the expanded file. |
| DD tests | `backend/tests/test_spo16_market_expansion.py` | Yes-only uses the recorded Yes. Yes+No and No-only stay inline. |
| Daily picks tests | `backend/tests/test_daily_analysis.py` | Bookmaker boards are derived from player_points. |
| SPO-98 wiring | `backend/tests/test_spo98_team_and_names.py` | Uses the shared loader. |
| Inventory | `backend/tests/test_spo106_recorded_fixtures.py` | Asserts the three NBA files, the posted markets, and the two markets that were not posted. |
| Docs | `docs/progress.md`, `backend/tests/fixtures/README.md` | SPO-106 row. Recorder contract. NBA only. |

## Why

A hand-typed bookmaker dict proves the code runs against a shape somebody remembered. The SPO-98 capture is a real `player_points` body, so every test that only needs that shape should start there. Relabeling a player or deleting Under is a derivation of that body. It is not a new response.

The expanded file is that other response. Tests copy a posted side and drop what the case does not need. They do not type a price the book did not post. `player_frees_made`, `player_field_goals`, and double-double No are still absent, so those builders stay.

## Tests

```
cd backend && pytest -q
```

`RUN_INTEGRATION` stays unset, so live tests do not call The Odds API.

The expanded body was committed as recorded. This run did not call The Odds API.

## Follow-ups

- WNBA fixture work stays deferred while WNBA work is paused.
- `player_frees_made`, `player_field_goals`, and double-double No are still inline. A later recording that actually posts those sides is what retires the `TODO(SPO-106)` builders.
- The group-props and daily-picks tests still rewrite player names and lines. Those values are the cases under test (threshold, consensus, team). The bookmaker shell is the recorded one.
