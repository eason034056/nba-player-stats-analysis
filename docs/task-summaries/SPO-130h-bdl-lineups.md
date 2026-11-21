# SPO-130h — NBA lineups from BALLDONTLIE projected_lineups

- Ticket: SPO-130h
- Branch: `feature/SPO-130h-bdl-lineups` (from `origin/dev` `416c00e`)

## Summary

NBA lineups now come from one BALLDONTLIE `GET /nba/v1/projected_lineups?game_ids[]=` fetch per slate. The RotoWire and RotoGrinders scrapers are gone, and there is no fallback to them. `/api/nba/lineups` and the event lineup badge still read `team_lineup_snapshots` through the existing `TeamLineup` shape. When `games`, `teams`, and `players` rows already exist, the same poll also writes `projected_lineups`, `projected_lineup_players`, and a `source_refreshes` row. A missing parent does not fail the live fetch, and that poll is not recorded as `complete = true`.

A complete five with no unresolved name is `confidence = "medium"`. A short five, or any unresolved starter, is `"low"`. `source_disagreement` is always false. There is no second source, so confidence is never `"high"`. `status` stays the completeness word (`projected` / `partial` / `unavailable`). `confirmation_status` is still computed at the API from `source_snapshots`. `"expected"` still lands on `"projected"`.

## Changes

| Area | File | Change |
|---|---|---|
| Provider | `backend/app/services/lineup_provider_bdl.py` | New. Calls existing `BdlClient.list_projected_lineups`. Chunks game ids at 12. Maps a recorded row onto `TeamLineup` through `normalize_source_players` / `make_source_lineup`. |
| Slate ids | same file | Sibling Redis key `lineup:v1:nba:slate-games:<date>`, TTL 36 hours, filled by one `list_games(dates=[slate], per_page=100)`. The tip cache is unchanged. |
| Live store | `backend/app/services/lineup_service.py` | `fetch_and_store` writes the BDL slate directly. Drops snapshot rows for teams this fetch did not return. Optional 002 write after the live write. |
| Name helpers | `backend/app/services/lineup_source_support.py` | Kept. HTML-only scrape helpers removed. `TEAM_ALIASES` and the roster cache stay. |
| Scrapers | `lineup_provider_rotowire.py`, `lineup_provider_rotogrinders.py` | Deleted. |
| Dependency | `backend/requirements.txt` | Removed the `requests` pin. Nothing else in the backend imports it. |
| Fixture | `backend/tests/fixtures/bdl/projected_lineups_21718081.json` | Recorded empty body, copied unchanged. |
| Tests | `backend/tests/test_spo130h_bdl_lineups.py` | Recorded OKC@POR, empty WAS@IND, chunking, unresolved name, parent / missing-parent writes. |
| Tests | `test_lineup_service.py`, `test_lineup_consensus.py`, `test_lineup_live_validation.py` | Scrape tests removed. Live call is `RUN_INTEGRATION=1` and does not print the key. |
| Comment | `backend/app/api/nba.py` | Events list still uses `peek_lineups`. The comment no longer says scrape. |
| Docs | `CLAUDE.md`, `README.md` | Live sources are The Odds API and BALLDONTLIE. |
| Docs | `docs/task-summaries/SPO-130h-bdl-lineups.md` | This file. |

`bdl_client.py`, `scheduler.py`, `odds_gateway.py`, `bdl_odds_provider.py`, migrations, `frontend/`, and `docs/progress.md` are not in this diff.

## Why

The two-site merge scored a single complete five as `confidence = "low"` whenever the other site was empty. Feeding BDL through that merge would have marked every real five low. The fetch now stores the BDL lineup as the slate. One source cannot disagree with itself, and it cannot earn `"high"` without a second independent list.

`list_projected_lineups` does not send `per_page` or a page token, because the recorded `game_ids[]` request does not. The recorded page size is 25. Twelve games are 24 team rows, so a longer slate is several calls of the existing method. A later capture that actually sends `per_page=100` can collapse that.

The SPO-144 tip key stays `{status, tips_utc}`. Game ids sit on `lineup:v1:nba:slate-games:<date>` so a lineup fetch does not call `list_games` again while that key is fresh, and so 130j can keep the tip key as it is. The three job ids and the pre-tip window are untouched. They already call `fetch_and_store`.

`team_lineup_snapshots` remains the live read. 002 is a second write for the point-in-time tables, and only when the foreign keys can succeed. `projected_lineup_players` references `players`, so a missing player skips that version the same way a missing game does. `source_refreshes.complete` is true only when every mapped version was written. An empty `data` list writes no 002 rows and does not mark the refresh complete. `game_lineups` is the post-game starter table and is not written here.

A team absent from `data` gets no lineup row. Snapshot rows for that date that this fetch did not return are deleted, so a cold events read does not keep a badge after BALLDONTLIE has nothing. `"expected"` is still not `"confirmed"`. No recorded body contains that status, so the test builds a snapshot dict instead of an HTTP envelope.

## Tests

```
cd backend && DATABASE_URL=<local throwaway> python -m pytest -q --tb=line
```

`1825 passed, 35 skipped, 4 xfailed, 0 failed` in 97.40s. The throwaway server is local. The suite was not pointed at `127.0.0.1:5434`.

The new tests use `projected_lineups_21718080.json` with `games_2026-11-10.json`, and `projected_lineups_21718081.json` with `games_2026-11-11.json`. OKC and POR are confirmed fives, `sources` is `["balldontlie"]`, disagreement is false, and a `team_lineup_snapshots` row is written. The empty body leaves `/api/nba/lineups` empty and the WAS@IND badge null. An abbreviated name that is not on the roster lands in `unresolved_starters`. Thirteen copies of a recorded game are requested as 12 ids, then 1. A second fetch on the same slate does not call `list_games` again. With parents present, the poll writes 2 `projected_lineups` rows and 10 players and `source_refreshes.complete` is true. With the game missing, or with players missing, the live snapshot still has both teams, `projected_lineups` stays empty, and `complete` is false. `game_lineups` stays empty.

`confirmation_status` was temporarily changed so a snapshot status of `confirmed` returned `"projected"`, then restored. `test_confirmed_okc_at_por_lineup_reaches_the_api` failed:

```
AssertionError: assert 'projected' == 'confirmed'
```

The live integration test is skipped unless `RUN_INTEGRATION=1` and `BALLDONTLIE_API_KEY` are set. It was not run here. It does not print the key.

`test_spo132b_optional_vpc.py::TestVpcIdConsole` is 3 skips on this machine (`terraform is not on PATH`). Those three are the known failures when terraform is installed. They are not from this change.

## Follow-ups

- Record a real `projected_lineups` body whose `status` is not `confirmed` before treating that word as an HTTP shape. `"expected"` stays a snapshot-dict test until then.
- A recorded `per_page=100` capture can replace the 12-id chunks.
- The live API still reads `team_lineup_snapshots`. Switching reads to `projected_lineups` is a later ticket, after the parent rows exist in production.
- `TeamLineupPanel` will show one source. The frontend is unchanged in this PR.

## Progress notes (for the docs PR)

| 票 | PR | 結果 |
|---|---|---|
| SPO-130h | 本 PR | NBA 先發改讀 BALLDONTLIE `GET /nba/v1/projected_lineups`。RotoWire 與 RotoGrinders 刮頁刪除，沒有 fallback。`/api/nba/lineups` 和賽事 badge 仍讀 `team_lineup_snapshots`。002 的 `projected_lineups` 只在 `games`、`teams`、`players` 都已存在時寫入；缺 parent 不讓這次抓取失敗，也不把 `source_refreshes.complete` 記成 true。沒有改 001/002，沒有寫 `game_lineups`。單一來源的完整五人信心是 `medium`，人數不足或有未解析名字是 `low`。SPO-144 的三個 job 與 tip cache 沒動。 |
