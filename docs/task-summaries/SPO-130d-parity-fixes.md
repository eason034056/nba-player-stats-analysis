# SPO-130d — parity fixes (cold-cache tip and pair points)

- Ticket: SPO-130d follow-up (QA #93 should-fix items)
- Branch: `feature/SPO-130d-parity-fixes` (from `origin/dev` `416c00e`)

## Summary

A props read that has not called `list_events` now loads the game with `GET /v1/games/{id}` and uses that `datetime` as the tip. Rows updated after tip are dropped. A failed game fetch raises, so an in-game board is not stored as a pregame board.

When BetParx and Bally Bet post two or more points totals for one player, the kept total is the one closest to the median of the other books' single lines. The old maximum is used only when no other book posted exactly one line. `nba_odds_provider` is still `theoddsapi`.

`scripts/record_bdl_odds_fixtures.py` can print same-slate agreement without writing files. The test and the script share `consensus_lines`.

## Changes

| Area | File | Change |
|---|---|---|
| Client | `backend/app/services/bdl_client.py` | `BdlClient.get_game`. `GET /v1/games/{id}`, no query. Returns the recorded `{"data": {game}}` object. A non-digit or non-positive id raises `BdlError` before HTTP. |
| Provider | `backend/app/services/bdl_odds_provider.py` | `_props_filtered` calls `get_game` when `_games` has no entry, stores `data` when it is a dict, then parses `datetime`. The error is not swallowed. |
| Adapter | `backend/app/services/bdl_props_adapter.py` | Pair points use the other books' median. `consensus_lines` is the shared vote. |
| Client test | `backend/tests/test_bdl_client.py` | `get_game` against `games__game1038278_record.json`: path `/v1/games/1038278`, empty query, body equals the recorded `response`. |
| Provider test | `backend/tests/test_spo130d_bdl_odds_provider.py` | Cold-cache t2 drop, warm cache does not call `get_game`, 40.5 alternate, max fallback, stats modes. |
| Recorder | `scripts/record_bdl_odds_fixtures.py` | `--stats-only` and `--from-fixtures`. Stats only. Exit 1 below 90% or when nothing is shared. |
| Docs | `docs/task-summaries/SPO-130d-parity-fixes.md` | This file. |

## Why

`list_events` is what used to fill `_games`. The gateway snapshot path calls `get_event_odds_with_usage` and does not call `list_events` on this provider. After a later `nba_odds_provider=balldontlie` flip, a cold in-game read would have kept every `updated_at`. Player-prop rows have `game_id` and `updated_at`, not the game's `datetime`. `list_games` needs a slate date, and guessing one from `updated_at` would be a new request shape. `GET /v1/games/{id}` is already recorded (`games__game*_record.json`). `data` is one object, not a list. No `games/21718080` file was added. Tests wrap the game object already stored in `games_2026-11-10.json` (`datetime` `2026-11-11T04:00:00.000Z`) as `{"data": game}`.

The old pair rule kept `max(lines)`. On the recorded OKC at Portland board that maximum is the real total, because the low total is the isolated one. A copied BetParx 33.5 row with `line_value` `40.5` used to win, and the real 33.5 was dropped. Other books on that board post 32.5 (FanDuel) and 33.5 (Caesars, BetMGM, BetRivers, DraftKings). The median is 33.5, so 33.5 stays and 40.5 goes. A vendor with two distinct totals is omitted from the median. Its main is ambiguous. Distance ties prefer the total the other books posted more often, then the lower total. Non-paired rows are not dropped. A player with one pair total is unchanged. The pair still collapses to one book.

When no other book has a single points total, the maximum remains. A shared low total plus a higher singleton has the same shape as a shared main plus a higher alternate, so there is no signal that beats the maximum. The maximum still drops the recorded isolated-low fake. The 40.5 failure is the case other books exist to fix.

`--stats-only` fetches one pregame pair inside the same 150 second budget and writes nothing. `--from-fixtures` reads `backend/tests/fixtures/same_slate` (or the directory given) and does not need a key. Both print the capture time, the shared count, the count and percent within 0.5, pass or fail against 90%, and those three numbers per market. They do not print a key, a raw body, or a player name. The vote is `consensus_lines`, which calls `DailyAnalysisService._group_main_votes` and `calculate_mode_threshold` and skips `player_double_double`. The pytest wrapper `_consensus` calls that same function.

`odds_gateway.py` is unchanged. The fix is in the provider. The default NBA path stays The Odds API.

## Tests

```
cd backend && DATABASE_URL="" python -m pytest -q --tb=line
```

`1638 passed, 252 skipped, 3 xfailed` in 17.08s, after merging `origin/dev` `439cbe7` (SPO-146 and SPO-147). `DATABASE_URL` was set to empty. This environment has no Docker and no local Postgres, so tests that open a database skipped. The session did not load a remote host. `test_spo132b_optional_vpc.py::TestVpcIdConsole` was 3 skipped here. Those three are known failures on a clean `origin/dev` when the console path actually runs. They did not fail in this run. The merge did not touch the files in this ticket. `odds_gateway.py` stays as SPO-146 left it.

`tests/test_bdl_client.py` and `tests/test_spo130d_bdl_odds_provider.py` together: `86 passed, 7 skipped`. The skips are the live client test, the unrecorded 429 file, and the same-slate pair, which is not in the tree.

Ruff `E9,F63,F7,F82` on the touched Python files: pass.

Mutation checks, then the code was restored:

1. Skip the cold-cache `get_game` (leave `game = None`). `test_cold_cache_loads_the_tip_and_drops_the_post_tip_board` failed: the t2 board was not empty (`AssertionError: assert [{...}] == []`).
2. Restore `return max(candidates)` for every pair. `test_a_higher_alternate_loses_to_the_other_books_median` failed: `assert [40.5] == [33.5]`.

- Integration test: SKIPPED. `RUN_INTEGRATION` is unset. `BALLDONTLIE_API_KEY` and `ODDS_API_KEY` were not used, so no live pair was recorded.
- Fabrication scan: PASS. `get_game` compares the body to `games__game1038278_record.json`. The cold-cache tip is the recorded object in `games_2026-11-10.json`, wrapped as `{"data": game}`. The 40.5 row is a copy of the recorded BetParx 33.5 over/under row with `line_value` and `id` changed. No new fixture file was committed. The stats test scores the adapter output of that recorded props file against itself, joined on the recorded game's teams and tip.
- Frontend: not touched.
- `docs/progress.md`: not touched.
- `nba_odds_provider`: not flipped.

## Follow-ups

Same-slate captures are raw API bodies and can be recorded on current `dev`. They are not in this PR. The official live measurement has to run on this branch, or on `dev` after this merges, because it has to use the median rule.

把這一節原樣放進 PR body / task summary 的 Follow-ups，方便他在自己的電腦上跑。兩把 key 都不要貼到聊天、commit，或終端除錯輸出裡。

### 一、同場對照（寫入 `tests/fixtures/same_slate/`，可在目前的 `dev` 上跑）

擷取的是兩邊 API 的原始回應，不依賴這次的 adapter 修正，所以現在的 `origin/dev` 就可以跑。檔案最好跟這支 follow-up PR 一起進 repo，這樣 CI 第一次跑對照測試時用的已是修正後的規則。

1. 本機更新到最新的 `origin/dev`（或這支 `feature/SPO-130d-parity-fixes` 分支）。
2. 確認環境裡有 `BALLDONTLIE_API_KEY` 與 `ODDS_API_KEY`。可以放在 repo 根目錄或 `backend/.env`；不要把它們貼到聊天裡。
3. 選一個還有尚未開打的 NBA 比賽的時段。腳本會挑最近一場兩邊用「美東日期 + 球隊代碼」對得上、且 BALLDONTLIE 狀態是 `scheduled` 的比賽，並且必須在 150 秒內抓完，否則不會存檔。
4. 在 repo 根目錄執行（不要加 `--bdl-only`）：

   `PYTHONPATH=backend python3 scripts/record_bdl_odds_fixtures.py`

5. 成功後，`backend/tests/fixtures/same_slate/` 會出現一組 `{日期}_{客}@_{主}__*.json`（含 Odds API、BALLDONTLIE 的 games/props/players，以及 `__meta.json`）。終端只會印 `wrote ... status=...` 和耗時，不應出現任何 key。
6. 把這組檔案交給這支 PR 一起提交。若腳本還去嘗試補空的 players/props 或 429 檔，已存在的檔案可忽略；這次要的是 `same_slate/`。

### 二、即時盤口對照（只印統計，請在這支 follow-up 分支或合併之後跑）

即時測量必須用修正後的假盤規則，請不要在未含這支 PR 的 `dev` 上當作正式門檻。

1. 切到 `feature/SPO-130d-parity-fixes`，或等它合併進 `dev` 後再跑。
2. 同樣準備好兩把 key，選一個尚未開打的時段。
3. 在 repo 根目錄執行：

   `PYTHONPATH=backend python3 scripts/record_bdl_odds_fixtures.py --stats-only`

4. 終端只應出現：擷取時間、共同盤口數、差距在 0.5 以內的數量與百分比、是否達到 90%、以及各市場的同樣三項數字。不要把完整 JSON、球員名單或 key 貼出來。把這段統計數字回傳或寫進 PR 即可。
5. 若要對已錄好的 `same_slate/` 再算一次相同統計（不需要 key）：

   `PYTHONPATH=backend python3 scripts/record_bdl_odds_fixtures.py --stats-only --from-fixtures backend/tests/fixtures/same_slate`

6. 檔案進 repo 之後，也可以跑既有測試（同樣會印整體同意率，低於 90% 會失敗）：

   `cd backend && DATABASE_URL="" PYTHONPATH=. python -m pytest tests/test_spo130d_bdl_odds_provider.py::TestRecordedSamples::test_same_slate_consensus_agrees_within_half_a_point -q`

門檻：共同盤口至少 90% 的共識線差距在 0.5 以內。同場對照進 repo、加上至少一次即時測量也過門檻，才是 130i 切換前的條件之一。

## Progress notes (for the docs PR)

- SPO-130d follow-up: a cold props read loads `GET /v1/games/{id}` and drops rows updated after tip. BetParx / Bally Bet points follow the median of the other books' single totals, and the maximum only when no other book posted one line. `nba_odds_provider` stays `theoddsapi`.

---

**Ticket**: SPO-130d
**Branch**: `feature/SPO-130d-parity-fixes`
**Task summary**: `docs/task-summaries/SPO-130d-parity-fixes.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges.
