# SPO-144 — NBA pre-tipoff lineup refresh window

- Ticket: SPO-144
- Branch: `feature/SPO-144-lineup-pretipoff-window`
- Base: `dev` (`6d9fa0a`)

## Summary

`lineup_fetch_pre_tipoff` keeps its job id and its 5-minute cadence. It scrapes only from the night's first NBA tip minus 2 hours until that tip. The cron is a wide Chicago grid, 09:00 through 23:55 every 5 minutes. The handler returns before `fetch_and_store` outside that window.

No games means no 5-minute scrape. A schedule that cannot be read logs one warning, caches that status for the slate, and skips the 5-minute window. The 15-minute `lineup_fetch_active_window` still runs. NBA injury refresh hours are unchanged. The WNBA 5-minute job is unchanged.

## Changes

| Area | What changed |
|---|---|
| NBA 5-minute job | Id stays `lineup_fetch_pre_tipoff`. Cron is America/Chicago `hour=9-23`, every 5 minutes. Handler is `_run_lineup_fetch_pre_tipoff_job`. |
| Window | `nba_lineup_pretipoff_in_window(now, first_tip_utc)` is true on `[first_tip - 2h, first_tip)`. The end is exclusive. |
| First tip | One `BdlClient.list_games(dates=[slate], per_page=100)` per `nba_slate_date()`. Cached in the process and in Redis at `lineup:v1:nba:first_tip:<date>` for 36 hours. Postponed games do not count. |
| Empty or failed schedule | `no_games` or `unreadable` is cached. The 5-minute scrape does not run. One warning on `unreadable`. |
| Injury comment | The block above `NBA_INJURY_REFRESH_TZ` states 11:00 through 00:59 Chicago as this job's own hours. `NBA_INJURY_REFRESH_HOURS`, `NBA_INJURY_REFRESH_CRON_HOUR` (`11-23,0`), and `NBA_INJURY_REFRESH_CRON_MINUTE` (`7,37`) are unchanged. |
| WNBA | `wnba_lineup_fetch_pre_tipoff` stays `hour=17,18,19` Chicago, every 5 minutes. |
| Tests | `backend/tests/test_spo144_lineup_pretipoff_window.py` |

## Why

The old cron was Chicago hours 22, 23, and 0. NBA tips are about 6:00–9:30 PM CT, so that window opened after the last tip. Late starter news lands in the two hours before the first tip, and the 5-minute job missed all of it. The 15-minute job (11:00–21:45 CT) was the only one crossing tip-off.

Two shapes were on the table. This PR uses the wide cron plus an early return, the same shape as `nba_injury_refresh_in_window`. One job id stays. Tests pass a fixed `now` and do not sleep or open a socket. A daily planner that adds date-triggers would drop the night if that planner failed, and the acceptance cases are the window edges, which the helper states directly.

The first tip comes from BALLDONTLIE `GET /v1/games?dates[]=`, one call per Eastern slate, not per tick. The Odds API events list is not used. That client records quota headers, and the events cache lives 5 minutes and includes the viewer offset, so it is not once per slate. A miss there would be another Odds API call. `per_page=100` covers one NBA date. The recorded 2026-11-11 page is a single page, so the job does not request another page.

A missing `BALLDONTLIE_API_KEY`, a failed `list_games`, or a body whose live games have no usable tip is `unreadable`. That status is cached for the slate, so later ticks do not call again and do not warn again. The 15-minute job never reads this cache. This skips the 5-minute window for the rest of that slate after one bad read. A fixed-hour fallback is the alternative, and it is not chosen here.

## WNBA coverage

`hour="17,18,19"` with a tick every 5 minutes fires from 5:00 PM CT through 7:55 PM CT.

A typical first tip of 7:00 PM ET is 6:00 PM CT. Chicago stays one hour behind Eastern in both standard time and daylight time. The dynamic window for that tip is 4:00 PM CT through 6:00 PM CT, not including 6:00. The fixed cron misses 4:00–5:00 PM CT, covers only 5:00–6:00 PM CT, and keeps firing until 7:55 PM CT, after that tip. It does not cover "first tip minus 2 hours." It starts one hour before a 7:00 PM ET tip.

A first tip at 8:00 PM ET (7:00 PM CT) would have its full two hours inside 17:00–19:00 CT, and the cron would still run until 7:55 PM CT, past that tip. WNBA is out of season in November. The job is not switched. `nba_lineup_pretipoff_in_window` does not take `league`. It only compares a clock to a tip. The games read is NBA-only.

## Tests

`cd backend && DATABASE_URL="" python3 -m pytest tests -q --tb=line`

1806 passed, 216 skipped, 6 xfailed, 0 failed.

The new file is 29 passed. Clocks are fixed. Bodies are the recorded files `games_2026-11-11.json` and `games__season1900_empty.json`. No live BALLDONTLIE or Odds API call. A 7:00 PM ET tip (standard time 2026-01-15, daylight time 2026-07-15, and the recorded 2026-11-11 slate) scrapes only from 4:00 PM CT until 6:00 PM CT. A 12:30 PM ET tip scrapes only from 9:30 AM CT until 11:30 AM CT. The tick at the tip does not scrape. No games does not scrape. A schedule error warns once, does not scrape, and the 15-minute handler still scrapes. WNBA registration stays at hours 17, 18, and 19. Injury hours and the injury tests were not edited.

`tests/test_spo132b_optional_vpc.py::TestVpcIdConsole` was 3 skipped here because `terraform` is not on PATH. Those three are the known failures when terraform is present. They did not fail in this run.

Mutation check: `NBA_LINEUP_PRETIPOFF_LOOKBACK` was changed from `timedelta(hours=2)` to `timedelta(hours=1)` and the new file was re-run. 8 failed, 21 passed. The constant was put back to 2 hours before the suite above. Failures included `test_standard_time_7pm_et_window_is_4pm_to_6pm_ct[now1-True]` (4:00 PM CT must be inside; with a 1-hour lookback it was outside), the daylight-time and matinee open edges, `test_recorded_nov11_slate_opens_at_4pm_ct`, `test_naive_now_is_read_as_utc`, `test_handler_fires_only_inside_the_window`, `test_recorded_slate_is_read_once_and_cached`, and `test_lookback_constant_is_two_hours`.

## Follow-ups

- [ ] Eason: later games the same night (a 9:30 PM ET tip, for example) get only the 15-minute refresh in their last 2 hours. Extend the 5-minute window to each game's tip minus 2 hours?
- [ ] Eason: an unreadable schedule skips the 5-minute window for the rest of that slate (the status is cached 36 hours). A fixed-hour fallback is the other choice. Not chosen here.
- [ ] The outer cron starts at 09:00 CT. A first tip before 11:00 AM CT loses the part of the window before 09:00. The 12:30 PM ET matinee (window from 09:30 CT) is inside the grid.
- [ ] WNBA: once Eason says so, pass that league's first tip into `nba_lineup_pretipoff_in_window`. The helper has no `league` argument. The 17–19 CT job stays until then.
- [ ] The one games read uses the default BALLDONTLIE client, which can retry a 429 or a 5xx before it raises. After it raises, the slate is cached as unreadable.

## Progress notes (for the docs PR)

| 票 | PR | 結果 |
|---|---|---|
| SPO-144 | 本 PR | NBA `lineup_fetch_pre_tipoff` 只在當晚第一場開賽前 2 小時到開賽這段，每 5 分鐘抓先發。沒有比賽或賽程讀不到就略過這段 5 分鐘，15 分鐘那條照跑。WNBA 仍是芝加哥 17–19。傷兵時段沒改。 |
