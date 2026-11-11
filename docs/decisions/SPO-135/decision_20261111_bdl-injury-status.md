# Decision — NBA pick injury status comes from the BALLDONTLIE cache

- **Ticket:** SPO-135c
- **Date:** 2026-11-11
- **Status:** Accepted

## Context

SPO-135 stopped copying `injury_status` off the projection row, so every NBA `DailyPick.injury_status` is null. `pick_signals.injury_blocks_combined` never fires, and an Out player still gets a `combined_probability`.

SPO-131 already normalizes BALLDONTLIE `/v1/player_injuries` into Redis key `injuries:nba:latest` (24h TTL, stale after 6 hours, 20-page cap, no write on a partial or empty walk). Doubtful is stored as Questionable and `raw_status` keeps the source word. The refresh was not registered, and NBA agents still defaulted to the ESPN/CBS scrape unless `NBA_INJURY_SOURCE` was `bdl`.

Policy (Eason, 2026-11-11): all NBA data comes from BALLDONTLIE. No new non-BALLDONTLIE NBA source. WNBA sources do not change. The shared trial key allows 5 requests per minute. The ML researcher's daily snapshot uses about 5 calls a day on the same key.

## Decision

1. `nba_injuries_refresh` is registered. It runs at :07 and :37 America/Chicago, hours 11 through 23 and hour 0. That is the existing NBA lineup slate window (11:00 through 00:59 Chicago, which is 12:00 through 01:59 America/New_York, the zone `nba_slate_date` uses). Two ticks an hour is one refresh every 30 minutes. `nba_injuries_refresh_minutes` is 30, and a snapshot younger than that is not fetched again. `misfire_grace_time` is 1 second, so a late boot does not catch up a missed tick. Outside the window the cron does not call.

2. Startup does not burst. A separate date job, `nba_injuries_startup_fill`, is scheduled at most once per process, one second after start. It calls the refresh with `force` only when `injuries:nba:latest` is absent. A present key, including a stale one, does not start a refresh. That one fill is the only path that may call outside the slate window.

3. No key means no call. The job logs `nba_injuries_refresh skipped; BALLDONTLIE_API_KEY is unset` and returns. Failures log the exception type only.

4. Every injury page goes through `BdlClient`, so the shared Redis limiter (`bdl:ratelimit:v1`, 5 per minute) governs the call. `PacedInjuryClient` waits 15 seconds between page starts. The first page is immediate. Any 60-second window therefore holds at most 4 calls from this job, leaving one slot for the researcher's snapshot. `max_instances` is 1.

   The injury client does not use the default three-attempt retry. A daily snapshot on another machine uses the same key, cannot see this Redis limiter, runs once between 4:45 and 5:30 PM CT, makes at most 5 calls spaced 20 seconds apart, and can land on :07. The schedule stays :07 and :37. `rate_limit_policy="injury"` allows two HTTP responses and one wait for the whole refresh. The wait is `Retry-After` when that header is a positive delay, otherwise the seconds until `x-ratelimit-reset` when that instant is still ahead, otherwise 30 to 59 seconds. The wait is capped at 60 seconds. A second 429 raises `BdlRateLimitError` with no further wait. The refresh logs that type once, writes nothing, and the previous snapshot stays. An empty key stays empty, so `injury_status` stays null. The refresh does not wrap the client in another retry loop. Worst-case extra sleep is 60 seconds, so the job cannot still be backing off when the next tick is due.

5. Worst case, the schedule is 14 hours times 2 ticks times the 20-page cap: 560 calls a day. One cold start that finds an empty key adds one more capped walk: 580. A walk that finishes earlier uses fewer calls. The steady state of the recorded first page plus a terminal page is 2 calls per tick, 56 a day, plus at most 20 on a cold start.

6. NBA `DailyPick.injury_status` is the normalized status from that snapshot (`Out`, `Questionable`, `Probable`, `Day-To-Day`). Doubtful stays Questionable on the field. `raw_status` is not a new API field. It is passed only into `build_nba_signals` / `combined_probability`. `injury_blocks_combined(status, raw_status)` blocks when either word, stripped and case-insensitive, is `out` or `doubtful`. An Out player, and a stored Doubtful, have `combined_probability` null. Name matching is `match_injury_entry`: a `bdl_player_id` wins; scraper rows and BALLDONTLIE rows that share one id use the first name match; two BALLDONTLIE rows with different ids, or the same name and no id, return no match. A miss or an ambiguous name leaves `injury_status` null. The code does not guess.

7. `select_daily_picks` keeps an NBA row whose own `injury_status` blocks (Out, or a literal Doubtful) when the sample floor passes, even though the blend is null, so the board can show the status. A cache Doubtful is stored as Questionable. Its blend is null, and the filter does not see `raw_status`, so that row leaves the board with the other null blends. A missing blend that is not an injury block still leaves the board.

8. If the cache is missing, stale, malformed, or the read raises, `injury_status` stays null and one warning is logged (kind or exception type; no key, URL, or message). Analysis still returns picks. WNBA does not load the snapshot. `lineup_confirmed` stays null.

9. NBA agent tools always read `injuries:nba:latest`. `NBA_INJURY_SOURCE` is removed. The env var is ignored. The ESPN/CBS scrape remains for WNBA and is not called for NBA. No request path calls BALLDONTLIE. Request paths only read Redis.

10. The team-id map is read from the recorded standings fixture (`tests/fixtures/bdl/standings_2026.json`). An unreadable file returns an empty map, and the refresh refuses to write. That is the production map until SPO-130d owns one.

## Alternatives

1. *Leave `NBA_INJURY_SOURCE` and flip the default to `bdl`.* Rejected. The scrape path would still be a live NBA source. Deleting the flag is a clean subtraction because WNBA keeps the scraper.
2. *Call `/v1/player_injuries` from daily analysis.* Rejected. The request path must not spend the shared 5-per-minute budget.
3. *Add `raw_status` to `DailyPick`.* Rejected. The board needs the normalized word. The source word exists only so the blend can still block on Doubtful.
4. *Keep a cache Doubtful on the filtered board.* Not in this change. The filter sees `injury_status` Questionable and a null blend, so the row is omitted. The stored pick still has a null blend. Showing that row would need the filter to see the source word.

## Tradeoff

The slate window matches the lineup jobs, so the snapshot is fresh while picks are being made and the key is idle overnight. A process that boots with an empty key spends one paced walk immediately, including outside the window, so the first request is not blind. A stale key waits for the next in-window tick. Event reads still pass `injury_status=None`, so an Out player can still receive a blend on `/reads` until that path reads the same snapshot.
