# SPO-144 — NBA and WNBA pre-tipoff lineup refresh windows

- Ticket: SPO-144
- Branch: `feature/SPO-144-lineup-pretipoff-window`
- Base: `dev` (`6d9fa0a`)

## Summary

`lineup_fetch_pre_tipoff` and `wnba_lineup_fetch_pre_tipoff` keep their job ids and their 5-minute cadence. Every game on today's Eastern slate gets its own window, `[that tip - 2 hours, that tip)`. The end is exclusive. Games do not share one window anchored on the earliest tip. Both crons are the wide Chicago grid, 09:00 through 22:55 every 5 minutes. Each handler returns before `fetch_and_store` when the clock is outside every game's window, and also when that Chicago minute is one the same league's 15-minute job already scrapes.

A 7:00 PM ET tip and a 9:30 PM ET tip open 4:00–6:00 PM CT and 6:30–8:30 PM CT. The gap (6:00–6:30 PM CT) does not scrape, and the tick at the later tip does not scrape. A one-game night is still one `[tip - 2 hours, tip)` window. A 12:30 PM ET matinee still opens 9:30–11:30 AM CT, and a later game that night has its own window. Chicago stays one hour behind Eastern in both standard time and daylight time, so the Chicago hours match on both.

No games means no 5-minute scrape. A missing key, or a body with no usable tip, logs one warning, caches that status for the slate, and skips the 5-minute window for the rest of that slate. There is no fixed-hour fallback. Eason decided that on 2026-11-21 for both leagues. A failed call (a 429 or a 5xx, after the client's own retries) is not cached. That tick does not scrape, the warning is once per slate in the process, and the next tick reads again. The 15-minute jobs still run. Inside Chicago hours 11 through 21, minutes 0, 15, 30, and 45 belong to those jobs, so the 5-minute handler returns before it reads the schedule. Hour 22 is outside that range, so 22:00 still scrapes when a window is open. NBA injury refresh hours are unchanged. WNBA opening (`wnba_lineup_fetch_opening`, 09:30 CT) and the 15-minute job (`wnba_lineup_fetch_active_window`, 11–21 CT) stay behind `wnba_jobs_enabled`. Both 15-minute registrations read `LINEUP_ACTIVE_WINDOW_CRON_HOUR` and `LINEUP_ACTIVE_WINDOW_CRON_MINUTE`.

## Changes

| Area | What changed |
|---|---|
| NBA 5-minute job | Id stays `lineup_fetch_pre_tipoff`. Cron is America/Chicago `hour=9-22`, every 5 minutes, last tick 22:55. Handler is `_run_lineup_fetch_pre_tipoff_job`. |
| WNBA 5-minute job | Id stays `wnba_lineup_fetch_pre_tipoff`. Same Chicago grid. Handler is `_run_wnba_lineup_fetch_pre_tipoff_job`. Opening and the 15-minute job still call `_run_wnba_lineup_fetch_job`. |
| Shared 15-minute ticks | `lineup_active_window_covers` expands `LINEUP_ACTIVE_WINDOW_CRON_HOUR` (`11-21`) and `LINEUP_ACTIVE_WINDOW_CRON_MINUTE` (`0,15,30,45`). Both 5-minute handlers return on a tick that set names. Both 15-minute registrations use the same two strings. |
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

A missing key, or a body with no usable tip, is `unreadable`. That status is cached for the slate, so later ticks do not call again and do not warn again. The 15-minute jobs never read this cache. Eason decided to skip the 5-minute window for the rest of that slate. A fixed-hour fallback is not used. A failed call is different: it is not stored, so a 429 or a 5xx on the first tick of the next slate does not turn off that night's windows. The next tick reads again.

Minutes 0, 15, 30, and 45 from 11:00 through 21:45 CT are already a scrape by `lineup_fetch_active_window` or `wnba_lineup_fetch_active_window`. The 5-minute handler of the same league returns on those ticks, before it reads the schedule, so the slate is not scraped twice. The covered hours and minutes come from the strings the 15-minute registration passes to `CronTrigger`. At 22:00 CT the 15-minute job is finished, so the 5-minute job still scrapes when a window is open. The hour field stops at 22 because no window reaches 23:00 CT.

## Tests

`cd backend && DATABASE_URL="" python3 -m pytest tests -q --tb=line`

1830 passed, 216 skipped, 6 xfailed, 0 failed.

The file is 53 passed. Clocks are fixed. NBA bodies are `games_2026-11-11.json` and `games__season1900_empty.json`. WNBA bodies copy `id`, `commence_time`, `home_team`, and `away_team` from `odds_api_events__basketball_nba.json` and only change `sport_key` and `commence_time`. No live BALLDONTLIE or Odds API call.

Standard time (2026-01-15) and daylight time (2026-07-15), for both leagues: a 7:00 PM ET tip and a 9:30 PM ET tip are open at 4:00–6:00 PM CT and at 6:30–8:30 PM CT, and closed in the gap and at the later tip. The 5-minute handler does not fetch on minute 0, 15, 30, or 45 while the Chicago hour is 11 through 21, because the 15-minute job already scrapes those ticks. 4:05 PM CT still scrapes. 09:30 CT still scrapes, because hour 9 is outside 11–21. A 12:30 PM ET matinee plus a 7:00 PM ET game opens 9:30–11:30 AM CT and 4:00–6:00 PM CT on both a standard-time date and a daylight-time date. A one-game night closes at that tip. Inside an open window, 18:00 CT does not fetch and 18:05 CT does, for both leagues. 22:00 CT inside a later window does fetch, because hour 22 is outside the 15-minute hours. No games does not scrape. A failed call warns once, does not scrape that tick, leaves Redis empty, and the next tick reads again. Those recovery clocks are 4:05 PM CT so they are not a 15-minute tick. A 429 and a 503 recover in the same process and after a new process that shares Redis. A body with no usable tip stays skipped for the slate. The 15-minute handler still scrapes. An empty Odds API key does not call `get_events`. The WNBA Redis key is `lineup:v1:wnba:tips:<date>`. A value under the NBA key is not used as the WNBA slate. WNBA opening stays 09:30 CT and the 15-minute job stays `hour=11-21`, `minute=0,15,30,45`. The 5-minute trigger is `hour=9-22`, not `hour=17,18,19`. Injury hours and the injury tests were not edited.

`tests/test_spo132b_optional_vpc.py::TestVpcIdConsole` was 3 skipped here because `terraform` is not on PATH. Those three are the known failures when terraform is present. They did not fail in this run.

Mutation check: `NBA_LINEUP_PRETIPOFF_LOOKBACK` was changed from `timedelta(hours=2)` to `timedelta(hours=1)`, then the whole `tests/test_spo144_lineup_pretipoff_window.py` file was re-run. 27 failed, 26 passed, out of 53. The constant was put back to 2 hours before the suite above. At `83ef553` the same whole-file check was 21 of 46. The file has grown since that commit, so 21 of 46 is the count for that commit, not for this head.

## Follow-ups

- [x] Eason, 2026-11-21: every game on the slate gets `[that tip - 2 hours, that tip)`, for NBA and for WNBA. The gap between two windows stays closed.
- [x] Eason, 2026-11-21: a missing key, or a body with no usable tip, skips the 5-minute window for the rest of that slate. No fixed-hour fallback. Same rule for WNBA.
- [ ] The outer cron starts at 09:00 CT. A tip before 11:00 AM CT loses the part of the window before 09:00. The 12:30 PM ET matinee (window from 09:30 CT) is inside the grid.
- [ ] The NBA games read uses the default BALLDONTLIE client, which can retry a 429 or a 5xx before it raises. After it raises, the slate is not cached, and the next tick reads again. The WNBA events client retries with no wait between attempts, then raises the same way.
- [ ] A failed call is not part of that pin: the next tick reads again. Eason has not decided this. QA review 6003790585, M1: the extra failed-call test file is waiting on Eason. It is not applied in this PR. A raised call is already left uncached, and the 36-hour TTL for a missing key or a body with no usable tip is unchanged.

## Progress notes (for the docs PR)

| 票 | PR | 結果 |
|---|---|---|
| SPO-144 | 本 PR | NBA 與 WNBA 的 5 分鐘先發抓取，都在該場開賽前 2 小時到該場開賽這段，時段改到芝加哥 09:00–22:55。11–21 點的 0、15、30、45 分交給 15 分鐘那條，5 分鐘那條不抓。22:00 仍抓。場與場之間的空檔不抓。沒有 key 或賽程內容沒有開賽時間，就略過這段 5 分鐘。呼叫失敗不寫進快取。傷兵時段沒改。 |
