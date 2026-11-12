# SPO-135a — US slate date, league on fetch logs, stale key note

- Ticket: SPO-135a
- Branch: `feature/SPO-135a-slate-date-fixes` (from `origin/dev` at `8b8bbdc`)
- Base: `dev`

## Summary

Schedulers and API defaults were using the UTC calendar date as the slate. After midnight UTC that is already the next day, while the US slate is still today. Those dates now come from `nba_slate_date()[0]` (America/New_York). `lineup_fetch_logs` and `odds_snapshot_logs` write `league`. The SPO-114 decision paragraph matches the unique key that includes `line`, and the writer keeps alternate rungs.

## Changes

| Area | File | Change |
|---|---|---|
| Clock | `backend/app/services/slate_date.py` | `nba_slate_date` and `offset_for_us_game_date` live here. One implementation. |
| Re-export | `backend/app/services/odds_snapshot_service.py` | Imports those two functions and re-exports them. `INSERT_LOG_SQL` writes `league` as `nba`. `snapshot_at` stays UTC. |
| Jobs | `backend/app/services/scheduler.py` | NBA and WNBA lineup jobs, `trigger_lineup_fetch_now`, and both daily-analysis jobs pass the US slate date. Projection jobs and `trigger_projection_fetch_now` are unchanged. |
| Analysis | `backend/app/services/daily_analysis.py` | `run_daily_analysis(date=None)` uses the US slate date. `analyzed_at` stays UTC. |
| NBA API | `backend/app/api/lineups.py`, `daily_picks.py`, `picks.py`, `nba.py` | Omitted date on lineups, daily picks, the bot picks route, and the events list is the US slate date. The event detail route still builds the caller's local date from `tz_offset`. |
| WNBA API | `backend/app/api/wnba.py` | Events, daily picks, and lineups use the same US slate date. WNBA sources are unchanged. |
| History | `backend/app/api/odds_history.py` | Imports `nba_slate_date` from `slate_date`. Behavior is unchanged. |
| Lineup logs | `backend/app/services/lineup_service.py` | `INSERT_FETCH_LOG_SQL` writes `self.league`. WNBA still does not write `team_lineup_snapshots`. Comments at the write and read gates match that. |
| Agent tool | `scripts/agents/tools/historical.py` | An omitted lineup date uses the US slate date. |
| Manual runner | `backend/test_daily_analysis.py` | Prints and analyzes the US slate date. |
| Decision | `docs/decisions/spo-114-bulk-props/decision_20261110_snapshot-only.md` | Paragraph 49 matches `UNIQUE (snapshot_at, event_id, player_name, market, bookmaker, line)` and the keep-alternates writer. The next sentence is unchanged. |
| Tests | `backend/tests/test_spo135a_slate_date.py` | Frozen 2026-11-11T00:30:00Z resolves to 2026-11-10. Frozen 2026-11-11T05:30:00Z resolves to 2026-11-11. WNBA fetch log and NBA snapshot log assert `league` against Postgres. |

## Why

A lineup or picks fetch after 6:00 PM Central (midnight UTC; 7:00 PM during daylight time) was asking for tomorrow's slate. The odds snapshot job already used America/New_York. The same clock now covers lineups, daily analysis, and the API defaults that mean "today's games."

`league` already exists on both log tables with default `'nba'`. Omitting it stored a WNBA lineup fetch as NBA. The odds snapshot writer is NBA-only, so its log writes `'nba'` explicitly.

The old decision sentence described a key with no `line` and a last-Over/last-Under writer. SPO-117 widened the key and stores each two-sided rung. The paragraph now says that. WNBA on `odds_line_snapshots` stays paused.

Projection prefetch still uses the UTC date. SPO-135 Phase 2 removes those jobs, and editing them here would collide with that PR.

## Tests / Verification

- Frozen clock `2026-11-11T00:30:00Z` (18:30 CST on 2026-11-10). `nba_slate_date` returns `('2026-11-10', -300)`. `GET /api/nba/lineups` with no date param, through `TestClient`:

```
status 200
{'date': '2026-11-10', 'team_count': 0, 'fetched_at': None, 'cache_state': 'fresh', 'lineups': []}
```

- The same suite freezes `2026-11-11T05:30:00Z` (23:30 CST, 00:30 EST) and expects `2026-11-11` for the lineup job, both daily-analysis jobs, `run_daily_analysis`, and the omitted-date API routes.
- Postgres: a WNBA `fetch_and_store` writes `lineup_fetch_logs.league = 'wnba'` and writes no `team_lineup_snapshots` row. An NBA `_log_snapshot` writes `odds_snapshot_logs.league = 'nba'`.
- Backend pytest: `cd backend && /tmp/nba-venv/bin/python -m pytest --tb=line -q` → 1327 passed, 24 skipped, 6 xfailed, 0 failed.
- Frontend: not touched.
- Integration test: SKIPPED (`RUN_INTEGRATION` unset). The new Postgres checks ran inside the unit suite and were not skipped.
- Fabrication scan: PASS. No hand-typed external API body. The lineup dict in the log test is local consensus input.

## Follow-ups

- [ ] Projection jobs, `trigger_projection_fetch_now`, and `api/projections.py` still default to the UTC date. Leave them for SPO-135 Phase 2.
- [ ] WNBA `team_lineup_snapshots` stay unwritten while that league is paused.
- [ ] `tz_offset` defaults are unchanged (480 on picks, 0 on the WNBA events list).
- [ ] `scripts/agents/date_utils.py` "today" still follows the process local zone. `test_agent_today_matches_the_pacific_game_date` stays xfailed.
