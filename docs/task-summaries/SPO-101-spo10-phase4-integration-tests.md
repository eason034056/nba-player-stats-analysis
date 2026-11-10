# SPO-101 — Phase 4 live integration tests: 12-tile event page + DD round-trip

**Status:** Implemented on `feature/SPO-101-spo10-phase4-integration-tests`; awaiting Eason squash-merge into `dev`.
**Parent epic:** [SPO-10](/SPO/issues/SPO-10) — event-page-stat-expansion (Phase 4 — Sentinel integration tests).
**Predecessors:** [SPO-16](/SPO/issues/SPO-16), [SPO-17](/SPO/issues/SPO-17), [SPO-18](/SPO/issues/SPO-18), [SPO-20](/SPO/issues/SPO-20), [SPO-26](/SPO/issues/SPO-26).
**Branch:** `feature/SPO-101-spo10-phase4-integration-tests` from `origin/dev`.

---

## Summary

Adds the Phase 4 `@pytest.mark.integration` coverage SPO-26 deferred: the 12 event-page markets against the live Odds API, plus a double-double round trip through the parser, `/props/no-vig`, and `/player-dd-history`. Tests skip unless `RUN_INTEGRATION=1`. They also skip, rather than fail, when `ODDS_API_KEY` is missing. Production code is unchanged. The live call was not executed in this environment because `ODDS_API_KEY` is unset.

## Changes

| File | Change |
|---|---|
| `backend/tests/test_spo101_event_page_integration.py` | New. 12 parametrized market-parse tests, one quota-budget test, one DD round-trip test. All `@pytest.mark.integration` and skipped unless `RUN_INTEGRATION=1`. |
| `docs/task-summaries/SPO-101-spo10-phase4-integration-tests.md` | This summary. |
| `docs/progress.md` | SPO-10 Phase 4 row and new SPO-101 row. |

## Why

Phase 4 of the event-page stat expansion (decision log, Sentinel scope) and the SPO-26 follow-up both ask for a live check of the 12-tile `/event` surface, not another mocked unit test. The Odds API bills per populated market, and FTM (`player_frees_made`) / FGM (`player_field_goals`) have historically returned `bookmakers: []` at 0 units. Treating that empty body as a failure would red-build the suite on a slate that is behaving as Scout measured. Empty means the parser wrote zero rows and did not invent a line. A posted market must come back as de-vigged rows whose fair probabilities sit in (0, 1) and sum to about 1.

The DD path cannot share the Over/Under parser. The round-trip sends the same live body through `_parse_binary_market` (via `_process_event`), then `POST /api/nba/props/no-vig` with `market=player_double_double`, then `GET /api/nba/player-dd-history`. The route is pointed at the already-fetched body so DD is not purchased twice. History is the CSV rate and has no threshold.

Quota per run, one NBA event:

| Call | Units |
|---|---|
| `GET /v4/sports/basketball_nba/events` | 0 (free) |
| `GET .../events/{id}/odds?markets=<all 12 keys in one URL>` | 1 per posted market, 0 per empty market. Expected **10** when FTM and FGM are empty. Ceiling **12**. Floor **0** if the slate has no props. |
| `POST /api/nba/props/no-vig` | 0 additional. Reuses the body above. |
| `GET /api/nba/player-dd-history` | 0. Local CSV. |

No new response fixture was saved. A fixture is recorded only from a real response, and this environment did not call the API.

## Tests / Verification

- Backend pytest, `RUN_INTEGRATION` unset, from `backend/` with Redis up: **611 passed, 20 skipped, 0 failed**. The 20 skips are the 14 new tests plus 6 pre-existing gated tests (`test_spo16_integration.py`, `test_wnba_odds_integration.py`, `test_lineup_live_validation.py`, `test_lineup_provider_rotowire_wnba.py`, and both tests in `test_quota_simulation.py`).
- New file alone, `RUN_INTEGRATION` unset: **14 skipped, 0 failed**.
- `RUN_INTEGRATION=1` with `ODDS_API_KEY` unset: **14 skipped, 0 failed**. Skip reason: `ODDS_API_KEY is not set; live Odds API tests skipped without calling the network`.
- `RUN_INTEGRATION=1` with a real key: **not run**. `ODDS_API_KEY` is unset in this environment. This is not a live pass.
- An in-memory parser/route smoke (not a saved fixture, not a live call) checked that `_process_event` and `POST /props/no-vig` agree on a two-leg DD quote and that `/player-dd-history` returns the CSV shape for Nikola Jokic (75 games, 61 DDs, `prob_dd` 0.8133). That smoke does not spend quota and is not a substitute for the live run.
- Production diff: none.
- No xfail. No live bug was observed, because the live call did not run.

## Follow-ups

- Run once locally before merge: `cd backend && RUN_INTEGRATION=1 ODDS_API_KEY=... pytest tests/test_spo101_event_page_integration.py -v`. Budget: 1 free events call + 1 odds call, expected 10 paid units, ceiling 12. If `player_field_goals` is posted and the median line is >= 10, that is the FGM-vs-FGA escalation from decision Addendum 1 Override 3; do not rename the metric inside this ticket.
- Hand-typed Odds API dicts still back the unit tests below. This ticket does not rewrite them. A later ticket can replace those dicts with captured `tests/fixtures/theoddsapi_<endpoint>__<variant>.json` files:
  - `backend/tests/test_odds_snapshot.py` (`_make_outcome` / `_make_market` / `_make_bookmaker`)
  - `backend/tests/test_odds_gateway.py` (`_sample_payload`)
  - `backend/tests/test_spo16_market_expansion.py` (`_dd_market_payload`, inline `fake_snapshot` bodies)
  - `backend/tests/test_daily_analysis.py` (inline `bookmakers_data` outcomes)
  - `backend/tests/test_daily_analysis_league.py` (inline outcomes)
  - `backend/tests/test_odds_theoddsapi.py` (small hand-typed `{"id", "bookmakers": ...}` stubs)
- Phase 5 (Lens) still has to confirm the integration test is in the diff, per the external-API review rule.
- Frontend `PlayerDDTile` still does not call `/player-dd-history` (SPO-26 follow-up). Out of scope here.

## Branch + PR

- Branch: `feature/SPO-101-spo10-phase4-integration-tests` (off `origin/dev`).
- PR target: `dev`.
- Merge: squash by Eason.
