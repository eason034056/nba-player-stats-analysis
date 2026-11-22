# SPO-130j — Pre-tip closing lines

- Ticket: SPO-130j
- Branch: `feature/SPO-130j-pretip-closing-lines` (from `origin/dev` `c409447`)

## Summary

A planner reads the existing tip cache `lineup:v1:nba:tips:<date>` and registers one `DateTrigger` per UTC tip minute. The alarm fires at tip minus 10 minutes. The job id is `odds_pretip:<date>:<HHMM>`. `replace_existing` is true, and `misfire_grace_time` is 8 minutes, so the scheduler's 1-hour default does not apply. The planner runs daily at 08:02 America/New_York, every 30 minutes, and about one second after process start. A second pass replaces the same ids. A `transient` tip read leaves alarms that are already registered. A minute that disappears from the tip list is removed.

The alarm talks to BALLDONTLIE only, through `balldontlie_nba_provider()`. It does not read `nba_odds_provider`. Each game is kept only when it is still `scheduled`, not postponed, in this UTC minute, and `now` is before its tip. Props are fetched once per remaining game. Rows with `updated_at` after tip are dropped by the same adapter rule as the live snapshot. Game odds are one `list_odds` for the slate, filtered to the remaining games. One `snapshot_at` (tip minus 10 minutes) is shared by the group. A Redis lock `odds:v1:pretip-lock:<date>:<HHMM>` (8 minutes) makes a second replica skip the group.

`odds_line_snapshots` is written first. `player_prop_snapshots` and `game_odds_snapshots` reuse `_write_bdl_live` with `snapshot_kind='closing'`. A missing parent is a counted miss. It does not fail the job or undo the line-table write. A retry at the same stamp updates those rows. `001_baseline.sql` and `002_bdl_core.sql` were not altered. The code default stays `theoddsapi`. `bdl_rate_limit_per_min` stays 5. There is no tip-minus-60 alarm. `docs/progress.md` was not edited.

## Changes

| Area | File | Change |
|---|---|---|
| Planner | `backend/app/services/scheduler.py` | Daily, 30-minute, and startup planner. One `DateTrigger` per tip minute at tip minus 10 minutes, grace 8 minutes, replace on the same id. |
| Closing job | `backend/app/services/odds_snapshot_service.py` | `take_closing_snapshot` and `closing_game_fate`. Shared live upsert now binds `snapshot_kind` as the last parameter. The live path still writes `live`. |
| Provider lookup | `backend/app/services/odds_gateway.py` | `balldontlie_nba_provider()` returns the BALLDONTLIE provider without reading `nba_odds_provider`. The module is imported inside that function. |
| Tests | `backend/tests/test_spo130j_pretip_closing_lines.py` | Planner, skips, post-tip drop, lock, and Postgres 16 through 005. |
| Docs | `docs/task-summaries/SPO-130j-pretip-closing-lines.md` | This file. |

## Why

The fixed Eastern snapshots can land long before tip or after the game has started. A closing line is the last price before tip. Grouping by UTC minute gives every game that tips together one shared stamp, and the unique key in `002` then makes a retry an update. The parent guard is the same one the live writer already uses, so a database that has the schema but not yet the game or player rows still keeps the `odds_line_snapshots` pass.

`snapshot_kind` is appended to the live tuple instead of prepended. The third prop value stays the book key, which the existing per-row retry test reads. The scheduled snapshot still passes `live`.

No recorded games file has `postponed: true`. The postponed test copies one 2026-11-11 game and flips that boolean only. Every other body is the recorded fixture, filtered by game id when a test needs one game.

## Tests

New file: 14 passed.

Full backend suite, with `DATABASE_URL` pointed at a local throwaway Postgres 16 (port 5432, not 5434):

```
1890 passed, 35 skipped, 4 xfailed
```

`test_spo132b_optional_vpc.py::TestVpcIdConsole`: 3 skipped (same clean-dev skip; terraform is not on this machine).

Postgres is 16.15 from the distro packages. Docker was not installed, so this was not a `postgres:16-alpine` container on port 5441. Migrations were applied through `005_bdl_pit.sql` by the scratch database fixture.

Mutation checks, then restored before the green suite:

1. Removed `misfire_grace_time` from the closing `DateTrigger`. `test_planner_schedules_one_alarm_per_tip_minute_and_replaces_on_restart` failed with `assert 3600 == (8 * 60)`. The job had inherited the scheduler default.
2. Removed the `game_tip <= now` branch in `closing_game_fate`. `test_now_at_tip_skips_without_a_props_fetch` failed with `assert 3 == 0` (`event_count` became 3 at the tip instant).

## Blast radius

- Every process that starts the scheduler registers the three planner jobs. A fresh tip cache uses the existing lineup reader, which calls `list_games` once and stores the result. A warm cache does not call it. A failed (`transient`) read does not delete alarms.
- At tip minus 10 minutes the job calls `get_player_props` once per remaining scheduled game and `list_odds` once for that slate, even while `nba_odds_provider` is `theoddsapi`. That spends the shared 5-per-minute BALLDONTLIE budget around tip. The 8-minute lock makes the other replica return without fetching.
- `odds_line_snapshots` now also receives this pre-tip pass, with the decimal game id as `event_id`. Readers that treat every row in that table as one of the three Eastern snapshots will also see this close.
- The live dual-write statement is the same statement. `snapshot_kind` is bound instead of hard-coded. Scheduled snapshots still store `live`. Opening rows are not written here.
- Eastern snapshot crons, `nba_odds_provider`, `bdl_rate_limit_per_min`, migrations `001` and `002`, and the cache-client fixture were not changed.

## Follow-ups

- Closing rows in the 002 tables appear only after `games` and `players` exist for that slate. `books` and `prop_markets` are already seeded by `002`. Until those parents exist, the job still writes `odds_line_snapshots` and counts the misses.
- This job does not write `odds_snapshot_logs`.
- Do not add a tip-minus-60 alarm. This ticket is tip minus 10 minutes only.

## Progress notes (for the docs PR)

| 票 | PR | 結果 |
|---|---|---|
| SPO-130j | 本 PR | 開賽前 10 分鐘的 closing 工作只打 BALLDONTLIE。規劃器每天、每 30 分鐘、以及行程啟動時讀 SPO-144 的 tip 快取（還新就不另外打 `list_games`），每個 UTC 開賽分鐘掛一個 `DateTrigger`，id 是 `odds_pretip:<date>:<HHMM>`，`replace_existing`，`misfire_grace_time` 是 8 分鐘，不是排程器預設的 1 小時。重啟會用同一組 id 重建。工作先確認比賽仍是 `scheduled` 且 `now < tip`，延期或非 `scheduled` 只記 log 並跳過。剩下的比賽各抓一次 props，整組再抓一次 game odds，`updated_at` 晚於 tip 的列丟掉。整組共用一個 `snapshot_at`（tip 減 10 分鐘）。Redis 鎖讓第二個 replica 不會再寫一次。`odds_line_snapshots` 先寫。`player_prop_snapshots` 與 `game_odds_snapshots` 沿用 130g 的 `_write_bdl_live` 與父列檢查，`snapshot_kind='closing'`。父列不在就計數跳過，不讓工作或 line 表失敗。同一 stamp 重跑是更新。沒有 tip 減 60 分。`nba_odds_provider` 預設仍是 `theoddsapi`，`bdl_rate_limit_per_min` 仍是 5。`001` 與 `002` 沒有改。 |

---

**Ticket**: SPO-130j
**Branch**: `feature/SPO-130j-pretip-closing-lines`
**Task summary**: `docs/task-summaries/SPO-130j-pretip-closing-lines.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges.
