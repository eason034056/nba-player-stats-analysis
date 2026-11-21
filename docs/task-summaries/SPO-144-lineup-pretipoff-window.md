# SPO-144 — NBA and WNBA pre-tipoff lineup refresh windows

- Ticket: SPO-144
- Branch: `feature/SPO-144-lineup-pretipoff-window`
- Base: `dev` (`6d9fa0a`)

## Summary

`lineup_fetch_pre_tipoff` and `wnba_lineup_fetch_pre_tipoff` keep their job ids and their 5-minute cadence. Every game on today's Eastern slate gets its own window, `[that tip - 2 hours, that tip)`. The end is exclusive. Games do not share one window anchored on the earliest tip. Both crons are the wide Chicago grid, 09:00 through 23:55 every 5 minutes. Each handler returns before `fetch_and_store` when the clock is outside every game's window.

A 7:00 PM ET tip and a 9:30 PM ET tip open 4:00–6:00 PM CT and 6:30–8:30 PM CT. The gap (6:00–6:30 PM CT) does not scrape, and the tick at the later tip does not scrape. A one-game night is still one `[tip - 2 hours, tip)` window. A 12:30 PM ET matinee still opens 9:30–11:30 AM CT, and a later game that night has its own window. Chicago stays one hour behind Eastern in both standard time and daylight time, so the Chicago hours match on both.

No games means no 5-minute scrape. A missing key, or a body with no usable tip, logs one warning, caches that status for the slate, and skips the 5-minute window for the rest of that slate. There is no fixed-hour fallback. Eason decided that on 2026-11-21 for both leagues. A failed call (a 429 or a 5xx, after the client's own retries) is not cached. That tick does not scrape, the warning is once per slate in the process, and the next tick reads again. The 15-minute jobs still run. NBA injury refresh hours are unchanged. WNBA opening (`wnba_lineup_fetch_opening`, 09:30 CT) and the 15-minute job (`wnba_lineup_fetch_active_window`, 11–21 CT) are unchanged and stay behind `wnba_jobs_enabled`.

## Changes

| Area | What changed |
|---|---|
| NBA 5-minute job | Id stays `lineup_fetch_pre_tipoff`. Cron is America/Chicago `hour=9-23`, every 5 minutes. Handler is `_run_lineup_fetch_pre_tipoff_job`. |
| WNBA 5-minute job | Id stays `wnba_lineup_fetch_pre_tipoff`. Same Chicago grid. Handler is `_run_wnba_lineup_fetch_pre_tipoff_job`. Opening and the 15-minute job still call `_run_wnba_lineup_fetch_job`. |
| Window | `nba_lineup_pretipoff_in_window(now, tips_utc)` is true when `now` is in `[tip - 2h, tip)` for any tip. Both leagues pass their tips. One datetime is a one-game night. `None` or an empty list is closed. The 2 hours are `NBA_LINEUP_PRETIPOFF_LOOKBACK`. |
| NBA tips | One `BdlClient.list_games(dates=[slate], per_page=100)` per `nba_slate_date()`. Cached at `lineup:v1:nba:tips:<date>` for 36 hours. Postponed games, and rows whose date is not the slate, do not count. |
| WNBA tips | One `get_events(league="wnba")` per slate. `commence_time` is the tip, kept when its Eastern slate date is that slate. Cached at `lineup:v1:wnba:tips:<date>` for 36 hours. The NBA key is not read or written. No BALLDONTLIE WNBA games client. |
| Old NBA key | `lineup:v1:nba:first_tip:<date>` is not read and is not written. |
| Empty or unreadable body | `no_games`, a missing key, and a body with no usable tip are cached as `unreadable` or `no_games`. The 5-minute scrape does not run for the rest of that slate. No fixed-hour fallback. Same rule for both leagues. |
| Failed call | A raised call returns `transient`. It is not written to memory or Redis. The next tick, including another process sharing Redis, reads again. The warning is once per slate in the process. |
| Injury comment | The block above `NBA_INJURY_REFRESH_TZ` states 11:00 through 00:59 Chicago as this job's own hours. The injury hour constants are unchanged. |
| Tests | `backend/tests/test_spo144_lineup_pretipoff_window.py` |

## Why

The old NBA cron was Chicago hours 22, 23, and 0. NBA tips are about 6:00–9:30 PM CT, so that window opened after the last tip. Late starter news lands in the two hours before a tip. The 15-minute job (11:00–21:45 CT) was the only one crossing tip-off.

This PR uses the wide cron plus an early return, the same shape as `nba_injury_refresh_in_window`. One job id stays per league. Tests pass a fixed `now` and do not sleep or open a socket.

The first cut stored only the earliest NBA tip, and left WNBA on fixed hours 17, 18, and 19. Those hours fire 5:00 PM CT through 7:55 PM CT, so a 7:00 PM ET tip (6:00 PM CT) lost 4:00–5:00 PM CT and kept firing after the tip. Eason decided on 2026-11-21 that every game, in both leagues, gets `[that tip - 2 hours, that tip)`. The gap between two windows stays closed.

NBA tips come from BALLDONTLIE `GET /v1/games?dates[]=`, one call per Eastern slate, not per tick. WNBA tips come from the events list the app already has, `get_events(league="wnba")`, one call per slate, not per tick. WNBA does not add a games client. NBA does not call the events list for this job. `per_page=100` covers one NBA date. The recorded 2026-11-11 page is a single page, so the NBA job does not request another page.

A missing key, or a body with no usable tip, is `unreadable`. That status is cached for the slate, so later ticks do not call again and do not warn again. The 15-minute jobs never read this cache. Eason decided to skip the 5-minute window for the rest of that slate. A fixed-hour fallback is not used. A failed call is different: it is not stored, so a 429 or a 5xx at 23:00 CT does not turn off the next day's windows. The next tick reads again.

## Tests

`cd backend && DATABASE_URL="" python3 -m pytest tests -q --tb=line`

1829 passed, 216 skipped, 6 xfailed, 0 failed.

The file is 52 passed. Clocks are fixed. NBA bodies are `games_2026-11-11.json` and `games__season1900_empty.json`. WNBA bodies copy `id`, `commence_time`, `home_team`, and `away_team` from `odds_api_events__basketball_nba.json` and only change `sport_key` and `commence_time`. No live BALLDONTLIE or Odds API call.

Standard time (2026-01-15) and daylight time (2026-07-15), for both leagues: a 7:00 PM ET tip and a 9:30 PM ET tip scrape at 4:00–6:00 PM CT and at 6:30–8:30 PM CT, and not in the gap or at the later tip. A 12:30 PM ET matinee plus a 7:00 PM ET game opens 9:30–11:30 AM CT and 4:00–6:00 PM CT on both a standard-time date and a daylight-time date. A one-game night closes at that tip. No games does not scrape. A failed call warns once, does not scrape that tick, leaves Redis empty, and the next tick reads again. A 429 and a 503 recover in the same process and after a new process that shares Redis. A body with no usable tip stays skipped for the slate. The 15-minute handler still scrapes. An empty Odds API key does not call `get_events`. The WNBA Redis key is `lineup:v1:wnba:tips:<date>`. A value under the NBA key is not used as the WNBA slate. WNBA opening stays 09:30 CT and the 15-minute job stays `hour=11-21`. The 5-minute WNBA trigger is `hour=9-23`, not `hour=17,18,19`. Injury hours and the injury tests were not edited.

`tests/test_spo132b_optional_vpc.py::TestVpcIdConsole` was 3 skipped here because `terraform` is not on PATH. Those three are the known failures when terraform is present. They did not fail in this run.

Mutation check: `NBA_LINEUP_PRETIPOFF_LOOKBACK` was changed from `timedelta(hours=2)` to `timedelta(hours=1)`, then these cases were re-run: `test_wnba_each_game_keeps_its_own_two_hour_window` (standard time and daylight time), `test_each_game_keeps_its_own_two_hour_window` (both dates), `test_recorded_two_tip_subset_has_a_gap`, and `test_lookback_constant_is_two_hours`. 6 failed. The constant was put back to 2 hours before the suite above. With a 1-hour lookback, 4:00 PM CT and 6:30 PM CT were outside. The WNBA job on each date scraped twice (5:55 PM CT and 8:25 PM CT) instead of five times. `test_recorded_two_tip_subset_has_a_gap` expected 6:30 PM CT to be inside and got outside.

## Follow-ups

- [x] Eason, 2026-11-21: every game on the slate gets `[that tip - 2 hours, that tip)`, for NBA and for WNBA. The gap between two windows stays closed.
- [x] Eason, 2026-11-21: a missing key, or a body with no usable tip, skips the 5-minute window for the rest of that slate. No fixed-hour fallback. Same rule for WNBA. A failed call is not part of that pin: the next tick reads again.
- [ ] The outer cron starts at 09:00 CT. A tip before 11:00 AM CT loses the part of the window before 09:00. The 12:30 PM ET matinee (window from 09:30 CT) is inside the grid.
- [ ] The NBA games read uses the default BALLDONTLIE client, which can retry a 429 or a 5xx before it raises. After it raises, the slate is not cached, and the next tick reads again. The WNBA events client retries with no wait between attempts, then raises the same way.

## Progress notes (for the docs PR)

| 票 | PR | 結果 |
|---|---|---|
| SPO-144 | 本 PR | NBA 與 WNBA 的 5 分鐘先發抓取，都在該場開賽前 2 小時到該場開賽這段。場與場之間的空檔不抓。沒有 key 或賽程內容沒有開賽時間，就略過這段 5 分鐘，不改走固定時段。呼叫失敗不寫進快取，下一輪再讀。15 分鐘那條照跑。傷兵時段沒改。 |
