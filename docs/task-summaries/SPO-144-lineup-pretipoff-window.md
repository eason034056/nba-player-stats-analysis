# SPO-144 — NBA pre-tipoff lineup refresh window

- Ticket: SPO-144
- Branch: `feature/SPO-144-lineup-pretipoff-window`
- Base: `dev` (`6d9fa0a`)

## Summary

`lineup_fetch_pre_tipoff` keeps its job id and its 5-minute cadence. Every NBA game on today's Eastern slate gets its own window, `[that tip - 2 hours, that tip)`. The end is exclusive. Games do not share one window anchored on the earliest tip. The cron is a wide Chicago grid, 09:00 through 23:55 every 5 minutes. The handler returns before `fetch_and_store` when the clock is outside every game's window.

A 7:00 PM ET tip and a 9:30 PM ET tip open 4:00–6:00 PM CT and 6:30–8:30 PM CT. The gap (6:00–6:30 PM CT) does not scrape, and the tick at the later tip does not scrape. A one-game night is still one `[tip - 2 hours, tip)` window. A 12:30 PM ET matinee still opens 9:30–11:30 AM CT, and a later game that night has its own window.

No games means no 5-minute scrape. A schedule that cannot be read logs one warning, caches that status for the slate, and skips the 5-minute window. The 15-minute `lineup_fetch_active_window` still runs. NBA injury refresh hours are unchanged. The WNBA 5-minute job is unchanged.

## Changes

| Area | What changed |
|---|---|
| NBA 5-minute job | Id stays `lineup_fetch_pre_tipoff`. Cron is America/Chicago `hour=9-23`, every 5 minutes. Handler is `_run_lineup_fetch_pre_tipoff_job`. |
| Window | `nba_lineup_pretipoff_in_window(now, tips_utc)` is true when `now` is in `[tip - 2h, tip)` for any tip. One datetime is a one-game night. `None` or an empty list is closed. |
| Tips | One `BdlClient.list_games(dates=[slate], per_page=100)` per `nba_slate_date()`. Cached in the process and in Redis at `lineup:v1:nba:tips:<date>` for 36 hours. The body is `status` plus `tips_utc`. Postponed games, and rows whose date is not the slate, do not count. Duplicate instants collapse to one. |
| Old key | `lineup:v1:nba:first_tip:<date>` is not read and is not written. A leftover value there is not the slate. |
| Empty or failed schedule | `no_games` or `unreadable` is cached. The 5-minute scrape does not run. One warning on `unreadable`. |
| Injury comment | The block above `NBA_INJURY_REFRESH_TZ` states 11:00 through 00:59 Chicago as this job's own hours. `NBA_INJURY_REFRESH_HOURS`, `NBA_INJURY_REFRESH_CRON_HOUR` (`11-23,0`), and `NBA_INJURY_REFRESH_CRON_MINUTE` (`7,37`) are unchanged. |
| WNBA | `wnba_lineup_fetch_pre_tipoff` stays `hour=17,18,19` Chicago, every 5 minutes. |
| Tests | `backend/tests/test_spo144_lineup_pretipoff_window.py` |

## Why

The old cron was Chicago hours 22, 23, and 0. NBA tips are about 6:00–9:30 PM CT, so that window opened after the last tip. Late starter news lands in the two hours before a tip, and the 5-minute job missed all of it. The 15-minute job (11:00–21:45 CT) was the only one crossing tip-off.

Two shapes were on the table. This PR uses the wide cron plus an early return, the same shape as `nba_injury_refresh_in_window`. One job id stays. Tests pass a fixed `now` and do not sleep or open a socket. A daily planner that adds date-triggers would drop the night if that planner failed, and the acceptance cases are the window edges, which the helper states directly.

The first cut of this PR stored only the earliest tip. Eason decided on 2026-11-21 that every game on the slate gets the same two hours. A later tip still needs the 5-minute scrape after the earlier tip has passed, and the gap between two windows stays closed. The cache key changed so a leftover single-tip value cannot be read as the whole slate.

The tips come from BALLDONTLIE `GET /v1/games?dates[]=`, one call per Eastern slate, not per tick. The Odds API events list is not used. That client records quota headers, and the events cache lives 5 minutes and includes the viewer offset, so it is not once per slate. A miss there would be another Odds API call. `per_page=100` covers one NBA date. The recorded 2026-11-11 page is a single page, so the job does not request another page.

A missing `BALLDONTLIE_API_KEY`, a failed `list_games`, or a body whose live games have no usable tip is `unreadable`. That status is cached for the slate, so later ticks do not call again and do not warn again. The 15-minute job never reads this cache. This skips the 5-minute window for the rest of that slate after one bad read. A fixed-hour fallback is the alternative, and it is not chosen here.

## WNBA coverage

`hour="17,18,19"` with a tick every 5 minutes fires from 5:00 PM CT through 7:55 PM CT.

A typical tip of 7:00 PM ET is 6:00 PM CT. Chicago stays one hour behind Eastern in both standard time and daylight time. The dynamic window for that tip is 4:00 PM CT through 6:00 PM CT, not including 6:00. The fixed cron misses 4:00–5:00 PM CT, covers only 5:00–6:00 PM CT, and keeps firing until 7:55 PM CT, after that tip. It does not cover "tip minus 2 hours." It starts one hour before a 7:00 PM ET tip.

A tip at 8:00 PM ET (7:00 PM CT) would have its full two hours inside 17:00–19:00 CT, and the cron would still run until 7:55 PM CT, past that tip. WNBA is out of season in November. The job is not switched. `nba_lineup_pretipoff_in_window` does not take `league`. It only compares a clock to a list of tips. The games read is NBA-only.

## Tests

`cd backend && DATABASE_URL="" python3 -m pytest tests -q --tb=line`

1812 passed, 216 skipped, 6 xfailed, 0 failed.

The file is 35 passed. Clocks are fixed. Bodies are the recorded files `games_2026-11-11.json` and `games__season1900_empty.json`. The two-tip gap keeps only the recorded rows whose `datetime` is `2026-11-12T00:00:00.000Z` (7:00 PM ET) and `2026-11-12T02:30:00.000Z` (9:30 PM ET). No live BALLDONTLIE or Odds API call.

Standard time (2026-01-15) and daylight time (2026-07-15): a 7:00 PM ET tip and a 9:30 PM ET tip scrape at 4:00–6:00 PM CT and at 6:30–8:30 PM CT, and not in the gap or at the later tip. The same edges hold on the recorded two-row subset, and the job scrapes at 4:00 PM, 6:30 PM, and 8:25 PM CT while skipping 6:00 PM and 6:15 PM CT, from one `list_games` call. A one-game night still closes at that tip. A 12:30 PM ET matinee plus a 7:00 PM ET game opens 9:30–11:30 AM CT and 4:00–6:00 PM CT. The full recorded 2026-11-11 slate stays open after the earliest tip (6:00 PM CT) because later tips cover it, and it closes at the last tip (9:00 PM CT). The stored Redis key is `lineup:v1:nba:tips:2026-11-11`. A value left under `lineup:v1:nba:first_tip:2026-11-11` does not stop the later-game scrape. No games does not scrape. A schedule error warns once, does not scrape, and the 15-minute handler still scrapes. WNBA registration stays at hours 17, 18, and 19. Injury hours and the injury tests were not edited.

`tests/test_spo132b_optional_vpc.py::TestVpcIdConsole` was 3 skipped here because `terraform` is not on PATH. Those three are the known failures when terraform is present. They did not fail in this run.

Mutation check: `NBA_LINEUP_PRETIPOFF_LOOKBACK` was changed from `timedelta(hours=2)` to `timedelta(hours=1)`, then these cases were re-run: `test_each_game_keeps_its_own_two_hour_window` (standard time and daylight time), `test_later_recorded_game_scrapes_after_the_first_tip`, `test_recorded_two_tip_subset_has_a_gap`, and `test_lookback_constant_is_two_hours`. 5 failed. The constant was put back to 2 hours before the suite above. With a 1-hour lookback, 4:00 PM CT (the open edge of the 7:00 PM ET window) and 6:30 PM CT (the open edge of the 9:30 PM ET window) were both outside. The recorded two-row job scraped once, at 8:25 PM CT, instead of three times. `test_recorded_two_tip_subset_has_a_gap` expected 6:30 PM CT to be inside and got outside.

## Follow-ups

- [x] Eason, 2026-11-21: every game on the slate gets `[that tip - 2 hours, that tip)`. Done in this PR. The gap between two windows stays closed.
- [ ] Eason: an unreadable schedule skips the 5-minute window for the rest of that slate (the status is cached 36 hours). A fixed-hour fallback is the other choice. Not chosen here.
- [ ] The outer cron starts at 09:00 CT. A tip before 11:00 AM CT loses the part of the window before 09:00. The 12:30 PM ET matinee (window from 09:30 CT) is inside the grid.
- [ ] WNBA: once Eason says so, pass that league's tips into `nba_lineup_pretipoff_in_window`. The helper has no `league` argument. The 17–19 CT job stays until then.
- [ ] The one games read uses the default BALLDONTLIE client, which can retry a 429 or a 5xx before it raises. After it raises, the slate is cached as unreadable.

## Progress notes (for the docs PR)

| 票 | PR | 結果 |
|---|---|---|
| SPO-144 | 本 PR | NBA `lineup_fetch_pre_tipoff` 在當晚每一場開賽前 2 小時到該場開賽這段，每 5 分鐘抓先發。場與場之間的空檔不抓。沒有比賽或賽程讀不到就略過這段 5 分鐘，15 分鐘那條照跑。WNBA 仍是芝加哥 17–19。傷兵時段沒改。 |
