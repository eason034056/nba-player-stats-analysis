# SPO-146 — WNBA removal cleanup

- Ticket: SPO-146
- Branch: `feature/SPO-146-wnba-removal-cleanup`
- Base: `dev` (`416c00ef58e467a8c8a2d537ca0de1f08210daac`)

## Summary

Finishes the five should-fix items from the #115 review. Dead WNBA branches, tests that opened deleted files, stale sentences, and 699 WNBA events in the ESPN schedule fixture are gone. The deploy docs now say how to flush the leftover local Redis keys. Migrations, `SCHEMA_SQL`, `odds_theoddsapi.py`, `ODDS_API_KEY`, and the frontend stay as they are.

## Changes

| Area | What changed |
|---|---|
| Hot keys | `prewarm_hot_keys` no longer has the unreachable `member_league == "wnba"` branch. `_league_from_hot_key` already returns `None` for an unregistered league, and that member is removed. `test_prewarm_drops_unregistered_league_members` stays. |
| Season tests | `test_spo97_rereview.py` keeps the NBA live-window check and drops the calls that opened deleted `wnba_2025.json` / `wnba_2026.json`. The unused Fever helper is gone. Docstrings no longer describe that recording. |
| CSV helpers | `_player_file` and `_rows_for` read `data/nba_player_game_logs.csv` only. Unused `_WNBA_*` event ids are gone from `test_spo97_season_edges.py` and `test_game_log_hygiene.py`. |
| Docstrings | Stale WNBA sentences are rewritten or removed in the SPO-98, SPO-104, SPO-111, SPO-113, SPO-122, SPO-131, SPO-135h, and SPO-137a tests, in `absence.py`, and in `game_log_hygiene.py`. The `recorded/` glob stays and does nothing when that directory is absent. |
| Fixture | `tests/fixtures/espn/schedule_events.json` is 4,183 events, compact JSON, same order, no `league == "wnba"`. `schedule_manifest.json` matches (`event_count` 4,183, no `wnba` key). `test_loaded_schedule_has_no_wnba_events` guards that. |
| Deploy docs | `docs/deployment/aws.md` and `docs/deployment/aws-steps-zh-TW.md` tell the operator to prefix-delete `events:wnba:*`, `daily_picks:wnba:*`, and `lineups:wnba:*` on local Redis (`no-vig-nba-redis`), and that `FLUSHDB` also drops current NBA keys, which the backend rebuilds. RDS is not part of the step. Startup does not flush Redis. |

## Why

After #115 the backend is NBA only, but a few branches and fixtures still pointed at files and leagues that are gone. The live-window test would raise `FileNotFoundError` under `RUN_INTEGRATION=1` before it called ESPN. The compact schedule still carried 699 WNBA events that no NBA hygiene path reads. The Redis flush was decided in SPO-145 and was not written into the deploy docs.

## Tests

`cd backend` and `python -m pytest --tb=line -q` with `DATABASE_URL` set to a throwaway Postgres 16 on `127.0.0.1:5441` (not `127.0.0.1:5434`, and not a bare `load_dotenv()` against the repo-root `.env`).

1840 passed, 35 skipped, 4 xfailed, 0 failed.

`test_spo132b_optional_vpc.py::TestVpcIdConsole` is the known set of 3 tests. They skipped in this run because `terraform` is not on PATH (`skipif` when `shutil.which("terraform")` is `None`). On a machine where terraform is present they fail the same way on clean `origin/dev`. This PR does not change that file.

Mutation: one event with `"league": "wnba"` was inserted at the front of `tests/fixtures/espn/schedule_events.json` (4,184 events). `test_loaded_schedule_has_no_wnba_events` failed at `assert all(event.get("league") != "wnba" for event in events)` (`assert False`). The fixture was restored byte-for-byte (4,183 events, zero `wnba`).

## Follow-ups

- Do not start SPO-130 or 130i here. `odds_theoddsapi.py` and `ODDS_API_KEY` stay.
- `001_baseline.sql`, `002_bdl_core.sql`, and `SCHEMA_SQL` still cite the old WNBA schema note and still allow `'wnba'` in `league_code`. Left alone. No `DELETE`.
- This PR does not flush Redis and does not touch RDS. The operator runs the new deploy step on the local Redis container.

## Progress notes (for the docs PR)

| 票 | PR | 結果 |
|---|---|---|
| SPO-146 | 本 PR | 清掉 #115 留下的死 WNBA 分支、會去開已刪檔案的測試、過期說明，並從 schedule fixture 拿掉 699 筆 WNBA 事件（剩下 4,183）。部署文件加上本機 Redis 的 `events:wnba:*`、`daily_picks:wnba:*`、`lineups:wnba:*` 前綴刪除；`FLUSHDB` 也會清掉目前的 NBA key，後端會重建。沒有改 migration、`SCHEMA_SQL`、`odds_theoddsapi.py`、前端，也沒有清 Redis 或 RDS。 |
