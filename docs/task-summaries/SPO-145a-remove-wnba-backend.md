# SPO-145a — remove the WNBA backend

- Ticket: SPO-145a
- Branch: `feature/SPO-145a-remove-wnba-backend`
- Base: `dev`

## Summary

The backend now serves NBA only. `/api/wnba` is gone. The four WNBA scheduler jobs are not registered. The WNBA CSV, the RotoWire WNBA parser, and `WNBA_JOBS_ENABLED` are gone. `odds_theoddsapi.py` and `ODDS_API_KEY` stay until 130i. The SQL `league` column still accepts `'wnba'` because BALLDONTLIE ids overlap. This PR does not edit a migration and does not DELETE rows.

Frontend pages that still call `/api/wnba` are SPO-145b. Those calls have to stop before or as this PR lands.

## Changes

| Area | What changed |
|---|---|
| Routes | Deleted `backend/app/api/wnba.py` and its `include_router`. |
| Scheduler | Removed `wnba_daily_analysis_job`, `wnba_lineup_fetch_opening`, `wnba_lineup_fetch_active_window`, `wnba_lineup_fetch_pre_tipoff`, and `wnba_jobs_enabled`. NBA lineup, injury, and odds jobs stay. |
| Odds | `League` and `SPORT_KEY_BY_LEAGUE` are NBA only. `PROVIDERS` has one entry. `odds_theoddsapi.py` stays. |
| Lineups | RotoWire is the NBA line-strip parser. `beautifulsoup4` and `lxml` are dropped. `wnba_lineup_service` is gone. |
| History | `wnba_csv_player_service`, `data/wnba_player_game_logs.csv`, and the ESPN WNBA fixtures used for that file are gone. |
| Cache | Events and daily-picks builders raise for any league other than `nba`. An NBA flush still leaves a leftover `daily_picks:wnba:*` key. |
| Docs | Deleted the dedicated WNBA research, decision, and task-summary files. Added `docs/decisions/SPO-145/decision_20261121_nba-only.md`. |

## Why

Eason is focusing on NBA. A second league in the odds client, the scheduler, and the CSV loader is product surface he is not using. The SQL domain stays wide because the id spaces overlap. Deleting The Odds API client in the same change would break NBA, which still defaults to that provider.

## Tests

`cd backend && DATABASE_URL="" python -m pytest --tb=line -q`

1600 passed, 222 skipped, 3 xfailed, 0 failed.

The 3 skips in `test_spo132b_optional_vpc.py::TestVpcIdConsole` are the terraform console checks. Terraform is not on PATH in this run, so they skip. On a machine where terraform is present they fail the same way on clean `origin/dev`. They are not caused by this removal.

Mutation: registering `wnba_lineup_fetch_opening` turned `test_registered_jobs_include_no_removed_lineup_ids` and `test_nba_pre_tipoff_triggers` red (`assert not ['wnba_lineup_fetch_opening']`). The registration was removed again. A process import of `app.main` has no `/api/wnba` route, and `SchedulerService.start()` does not register the four WNBA job ids.

## Follow-ups

- SPO-145b must stop the frontend from calling `/api/wnba/*`.
- At deploy, flush Redis keys `events:wnba:*`, `daily_picks:wnba:*`, `lineups:wnba:*`, and hot-key members whose sport is `basketball_wnba`. This PR does not flush Redis and does not touch RDS.
- Stored WNBA rows, if any, stay until the 138 wipe. Do not DELETE them here.
- 130i still owns removal of `odds_theoddsapi.py` and `ODDS_API_KEY`.

## Progress notes (for the docs PR)

| 票 | PR | 結果 |
|---|---|---|
| SPO-145a | 本 PR | 後端拿掉 WNBA route、四個 WNBA 排程、WNBA CSV 與 RotoWire parser。SQL `league` 仍可存 `'wnba'`（id 會重疊），沒有改 migration、沒有 DELETE。`ODDS_API_KEY` 與 Odds API client 留到 130i。部署時再清 Redis 的 `events:wnba:*`、`daily_picks:wnba:*`、`lineups:wnba:*`。前端呼叫要等 SPO-145b。 |
