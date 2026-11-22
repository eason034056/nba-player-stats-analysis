# SPO-130g — NBA snapshot jobs, daily analysis, prewarm, and live dual-write

- Ticket: SPO-130g
- Branch: `feature/SPO-130g-nba-jobs-bdl` (from `origin/dev` `a29eb8b`)

## Summary

When `nba_odds_provider` is `balldontlie`, the odds snapshot job and daily analysis list the day's NBA games through `odds_gateway.list_events`. A game is kept only when its status is `scheduled`, its tip is still ahead of `now`, and the tip falls on the requested local date. The Odds API path still calls `odds_provider.get_events` and does not apply that tip filter, so historical fixture dates stay green.

Daily analysis under Ball Don't Lie asks `get_market_snapshot` once per game with `SNAPSHOT_MARKETS`. A fresh snapshot cache is zero upstream calls. Each supported market is sliced from that body in memory. The Odds API path still asks once per market.

`prewarm_hot_keys` skips a hot key whose stored `provider` does not match the active provider for that league. The member stays in the set. A member with no provider is still warmed.

`GET /api/metrics` reads `PROVIDERS["nba"].rate_status()`. Under the default `theoddsapi` that is the same object as before. The JSON keys are unchanged.

`odds_line_snapshots` is still written. Event ids are the decimal game id under Ball Don't Lie. When that provider is on and Postgres is connected, the same snapshot also writes `player_prop_snapshots` and `game_odds_snapshots` with `snapshot_kind = 'live'` and `league = 'nba'`. A row is inserted only when the parent `games`, `players`, `books`, and `prop_markets` rows exist. A missing parent is logged as `bdl_live_parent_miss` and counted. It does not fail `take_snapshot` or the line-table write. A retry at the same `snapshot_at` updates the live tick. `001_baseline.sql` and `002_bdl_core.sql` were not altered. `bdl_rate_limit_per_min` stays 5.

## Changes

| Area | File | Change |
|---|---|---|
| Gateway | `backend/app/services/odds_gateway.py` | `active_nba_provider_name()`. Prewarm skips a hot key stored for a different provider and does not delete it. |
| Snapshot | `backend/app/services/odds_snapshot_service.py` | Ball Don't Lie event list, pre-tip filter, and 002 live dual-write with the parent guard. |
| Provider body | `backend/app/services/bdl_odds_provider.py` | Cached odds body includes `player_ids` so the live write can see them after the props call. |
| Daily analysis | `backend/app/services/daily_analysis.py` | Same event filter. One combined market fetch per game, then a per-market slice. |
| Metrics | `backend/app/api/metrics.py` | Quota comes from `PROVIDERS["nba"]`. |
| Tests | `backend/tests/test_spo130g_nba_jobs_bdl.py` | Call counts, filters, both providers, prewarm, metrics, and Postgres 16 through 005. |
| Docs | `docs/task-summaries/SPO-130g-nba-jobs-bdl.md` | This file. `docs/progress.md` was not edited. |

## Why

The events routes already followed `nba_odds_provider`. The snapshot job and daily analysis still called The Odds API, so flipping the flag did not change those jobs, and the 002 live tables stayed empty. The parent check matches the lineup writer: a database that has the schema but not yet the game and player rows must not fail the capture that `odds_line_snapshots` already stored.

Over/under rows store both prices and leave `milestone_odds` null. `player_double_double` is `milestone`: the Yes price is `milestone_odds`, both sides are null, and the line is `0.5`. That is the shape `002` checks and the `005` trigger requires. One main line per player, book, market, and snapshot time. Game lines come from `BdlClient.list_odds` for the slate date. The recorded odds file is the 2026-11-11 request. The test copies those rows onto game `21718080` and changes only `game_id`, because that file has no row for the open 2026-11-10 game. Vendors that are not in the `books` seed, including `polymarket` and `kalshi`, are counted misses.

If Postgres is disconnected, the snapshot still calls `list_odds` once for an open slate and inserts nothing. The props call has already happened by then. An empty slate does not call it.

## Tests

```
cd backend && DATABASE_URL=<throwaway local Postgres 16 on 127.0.0.1:5441> REDIS_URL=redis://127.0.0.1:6399/0 python -m pytest --tb=line -q
```

`1867 passed, 35 skipped, 4 xfailed`. Not port 5434. The database was migrated through `005`. `REQUIRE_DOCKER_TESTS` was unset, so the docker verify skipped. The three `test_spo132b_optional_vpc.py::TestVpcIdConsole` cases skipped because terraform is not on PATH. They did not fail.

Mutation, then restored before the suite above:

- `bdl_event_is_open` ignored status. `test_snapshot_calls_one_games_list_and_props_only_for_the_open_game` failed with 6 `get_player_props` calls instead of 1.
- `_props_with_parents` sent every prop row to the insert. `test_missing_parents_still_write_digit_line_rows` failed because the log contained `batch skipped`. The line-table write still completed and `take_snapshot` did not raise.

Integration test: SKIPPED. No new client and no live call. Bodies are `backend/tests/fixtures/bdl/`. Fabrication scan: PASS. The only edited field on a recorded odds row is `game_id`.

WNBA tests stayed in the green suite. This change does not add a WNBA provider.

## Blast radius

- Snapshot `_get_events` and daily `_get_events_for_date` still call `odds_provider.get_events` when the provider is `theoddsapi`. The tip filter runs only for `balldontlie`.
- Daily analysis still makes one `get_market_snapshot` call per supported market on The Odds API. The single combined call is only for `balldontlie`.
- Prewarm still warms a member that has no `provider` field. A mismatch is skipped, not removed, for the five-minute window.
- Metrics under the default provider reads the same `odds_provider` object as before.
- `bdl_parent_misses` is added to the snapshot result only when the provider is `balldontlie`.
- No migration, no production flag flip, no change to the rate-limit default.

## Follow-ups

- Do not set `NBA_ODDS_PROVIDER=balldontlie` in production until the cutover. The code default stays `theoddsapi`.
- Live rows appear only after `games` and `players` exist for that slate. `books` and `prop_markets` are already seeded by `002`.

## Progress notes (for the docs PR)

| 票 | PR | 結果 |
|---|---|---|
| SPO-130g | 本 PR | 快照工作與 `daily_analysis` 在 `balldontlie` 時改走 `odds_gateway.list_events`，只留 `scheduled` 且開賽時間還沒到的比賽。每日分析對一場比賽只抓一次 `SNAPSHOT_MARKETS`，快取還新就不再打上游。hot-key 預熱跳過另一個 provider 留下的鍵，不刪除。`/api/metrics` 改讀 `PROVIDERS["nba"].rate_status()`。資料庫有連線時，同一張快照另外寫 002 的 `live` 列（`player_prop_snapshots`、`game_odds_snapshots`），但 `games`、`players`、`books`、`prop_markets` 缺父列就計數並跳過，不讓 `take_snapshot` 或 `odds_line_snapshots` 失敗。`over_under` 兩邊都有賠率且 `milestone_odds` 是空的；`player_double_double` 是 `milestone`，Yes 價在 `milestone_odds`，線是 `0.5`。重跑同一個 `snapshot_at` 會更新而不是再插一列。`001` 與 `002` 沒有改。程式預設仍是 `theoddsapi`，`bdl_rate_limit_per_min` 仍是 5。 |

---

**Ticket**: SPO-130g
**Branch**: `feature/SPO-130g-nba-jobs-bdl`
**Task summary**: `docs/task-summaries/SPO-130g-nba-jobs-bdl.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges.
