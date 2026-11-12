# SPO-135c — NBA pick injury status from BALLDONTLIE

- Ticket: SPO-135c
- Branch: `feature/SPO-135c-bdl-injury-status` (from `origin/feature/SPO-135-remove-sportsdataio`, then a merge of `origin/feature/SPO-131-bdl-injuries`)
- Base: `dev`
- Stacks on PR #69. Includes the SPO-131 commits. Supersedes PR #60.

## Summary

NBA `DailyPick.injury_status` is the normalized status from Redis key `injuries:nba:latest`. Out, and a source word of Doubtful, set `combined_probability` to null. Questionable, Probable, and Day-To-Day keep a blend. A missing, stale, malformed, or unreadable snapshot leaves the field null and logs one warning. Analysis still returns picks. `lineup_confirmed` stays null. WNBA picks and the WNBA agent injury scrape are unchanged.

`nba_injuries_refresh` runs at :07 and :37 America/Chicago during the lineup slate window (11:00 through 00:59). Pages go through `BdlClient` and a 15-second pace, so this job uses at most 4 of the shared 5 requests per minute. A startup fill runs once, and only when the key is absent.

The injury client retries one HTTP 429. The wait is `Retry-After`, or a future `x-ratelimit-reset`, or 30 to 59 seconds, and it is at most 60 seconds. A second 429 leaves the previous snapshot in place and logs the exception type once. The default client still retries three times for every other caller. The other machine's snapshot (4:45 to 5:30 PM CT, at most 5 calls, 20 seconds apart) can land on :07 and cannot see this Redis limiter. The schedule does not move.

## Why

After SPO-135, `injury_status` was always null, so `injury_blocks_combined` never fired and Out players still received a blend. Policy is that NBA data comes from BALLDONTLIE. The cache and the normalizer already exist on SPO-131. This change registers the job and copies the snapshot onto the pick. #69, this PR, and a paired frontend PR merge together so Out players are not published in between.

## Changes

| Area | What changed |
|---|---|
| Scheduler | `nba_injuries_refresh` at :07 and :37 Chicago, hours 11-23 and 0. `misfire_grace_time` 1. `nba_injuries_startup_fill` once per process when the key is missing |
| Client | `refresh_nba_injuries_from_bdl` wraps `BdlClient` in `PacedInjuryClient` (15s between pages) and uses the recorded standings map |
| Daily picks | NBA loads the snapshot once. `match_injury_entry` sets `injury_status`. `raw_status` is passed only into the signal builder. Out stays on the filtered board with a null blend |
| Agents | NBA always reads the cache. `NBA_INJURY_SOURCE` is removed. WNBA still scrapes ESPN/CBS |
| Settings | `nba_injuries_refresh_minutes` default 30. Duplicate `balldontlie_api_key` from the merge removed |
| Docs | This summary and `docs/decisions/SPO-135/decision_20261111_bdl-injury-status.md`. SPO-131 decision gets a one-line superseded note |

## What changed from SPO-131

- The source flag is gone. NBA does not scrape. WNBA still does.
- The job is registered. The interval is 30 minutes inside the slate window, not the unused 15-minute setting.
- HTTP goes through `BdlClient` and the shared Redis limiter, plus the 15-second page gap.
- Team ids come from the recorded standings fixture.
- Doubtful still maps to Questionable. Picks now block on `raw_status`.
- Empty, partial, and failed walks still do not overwrite. Logs are still the exception type only.
- Request paths still only read Redis.

## Tests / Verification

Recorded fixtures only. No live BALLDONTLIE or Odds API call.

- `cd backend && python3 -m pytest tests -q --tb=line` → 1347 passed, 28 skipped, 6 xfailed, 0 failed.
- NBA pick signals and event reads omit the projection key. Market, last-10, history, and defense still serialize as null when those inputs fail. WNBA picks still have `signals` null and `combined_probability` null. The blend is unchanged because a missing projection already added zero.
- A recorded 429 (`lineups_18447393_2026-01-15_agents_429.json`) is retried once, waits for `x-ratelimit-reset`, then leaves the previous snapshot in place and logs one `BdlRateLimitError` warning. A later 429 in the same refresh does not wait again.
- `cd scripts/agents && python3 -m pytest tests -q --tb=line` → 114 passed.
- Redis on localhost, snapshot seeded by `refresh_nba_injuries_from_bdl` with a mocked transport over `tests/fixtures/bdl/player_injuries__page1.json` and a terminal copy. Odds gateway served the recorded `player_points` body with one description relabeled to Jimmy Butler (Out on that page). `GET /api/health` 200. `GET /api/nba/daily-picks?date=2026-11-10&tz_offset=480&min_probability=0.5&min_games=5` 200, 12 picks. Jimmy Butler `injury_status` `Out`, `combined_probability` null, `lineup_confirmed` null. Dyson Daniels `injury_status` null, `combined_probability` 0.743.

## Follow-ups

- [x] Event reads still passed `injury_status=None`. Closed by SPO-135e: `/reads` loads the same snapshot.
- [ ] The filtered board drops a cache Doubtful (status Questionable, blend null) because the filter does not see `raw_status`.
- [ ] SPO-130d: a production team-id map. This PR reads the recorded standings fixture.
- [ ] Paired frontend PR: `injury_status` is non-null again for a matched NBA player. `lineup_confirmed` stays null.
- [ ] ML integration must re-add the projection slot on NBA picks and event reads.
- [ ] Close PR #60 after this merges. Merge #69 first, then this PR. After #69 squash-merges, `git merge origin/dev` on this branch.
