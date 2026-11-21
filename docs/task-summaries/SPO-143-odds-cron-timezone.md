# SPO-143 — Odds snapshot crons on Eastern wall-clock time

- Ticket: SPO-143
- Branch: `feature/SPO-143-odds-cron-timezone` (from `origin/dev` at `6d9fa0a`)
- Base: `dev`

## Summary

`odds_snapshot_early`, `odds_snapshot_mid`, and `odds_snapshot_final` inherited the scheduler's UTC timezone. The hours `16:05`, `22:05`, and `23:35` UTC match 11:05 AM, 5:05 PM, and 6:35 PM Eastern only during standard time. Under daylight time the final run is 7:35 PM ET, after 7:00 and 7:30 PM tip-offs, so the pre-lock snapshot can hold in-game lines. The three triggers now pass `timezone="America/New_York"` at 11:05, 17:05, and 18:35. Job ids are unchanged. The scheduler default stays `timezone="UTC"`.

## Changes

| Area | File | Change |
|---|---|---|
| Jobs | `backend/app/services/scheduler.py` | The three odds snapshot `CronTrigger`s use `timezone="America/New_York"` at 11:05, 17:05, and 18:35. The comment above them matches those times and states the UTC equivalent under EST and under EDT. The startup line names the same Eastern clock. `AsyncIOScheduler(timezone="UTC")` and every other job are unchanged. |
| Tests | `backend/tests/test_spo143_odds_cron_timezone.py` | Next fire time from a July date and a January date is the same Eastern wall clock. The July final run is before 7:00 PM ET. The comment and the startup line match that clock. |

## Why

Closing-line value needs a pre-lock price. A final capture at 7:35 PM ET is after tip-off on a 7:00 or 7:30 slate, so any CLV taken from it mixes the close with in-game lines. The old UTC hours were already the right Eastern clock in January (EST, UTC-5): 16:05, 22:05, and 23:35 UTC are 11:05, 17:05, and 18:35 ET. Daylight time (EDT, UTC-4) shifts that same UTC schedule one hour later. Putting the zone on the trigger, the way the lineup jobs pass `timezone="America/Chicago"`, keeps the wall clock and lets the zone database apply the transition.

The scheduler default stays UTC. `daily_analysis_job` is `CronTrigger(hour=12, minute=0)` with no zone of its own, so it follows that default. Moving the scheduler to Eastern would move that job and any other trigger that does not pass a zone.

## Tests / Verification

- New file, no sleep and no network. Each test calls `trigger.get_next_fire_time(None, <aware datetime>)`.
  - `2026-07-15 00:00 America/New_York` (EDT) and `2026-01-15 00:00 America/New_York` (EST) both fire at 11:05, 17:05, and 18:35 Eastern on that calendar date.
  - The final July fire time is before `2026-07-15 19:00 America/New_York`.
  - `AsyncIOScheduler` is still constructed with `timezone="UTC"`.
- Mutation check: removed `timezone="America/New_York"` from `odds_snapshot_final` only (`hour=18`, `minute=35` left in place) and restored it afterward. This machine's local zone is UTC, which is what APScheduler uses when a `CronTrigger` has no timezone. `DATABASE_URL="" python -m pytest tests/test_spo143_odds_cron_timezone.py -k july` then failed:

```
AssertionError: odds_snapshot_final next fire from 2026-07-15T00:00:00-04:00 is 2026-07-15T14:35:00-04:00, expected 18:35 America/New_York
assert (14, 35, 0) == (18, 35, 0)
```

14:35 EDT is 18:35 UTC. The argument is back on the trigger. The same file passed again after the restore (6 passed).

- Backend pytest: `cd backend && DATABASE_URL="" python -m pytest --tb=line -q` → 1783 passed, 216 skipped, 6 xfailed, 0 failed (22.92s). WNBA scheduler tests in `test_spo130b_wnba_jobs_flag.py` passed. The 3 `test_spo132b_optional_vpc.py::TestVpcIdConsole` tests skipped because `terraform` is not on PATH. They did not fail in this run.
- Frontend: not touched.
- Integration test: SKIPPED (`RUN_INTEGRATION` unset).
- Fabrication scan: PASS. No external API body. The tests build `CronTrigger` objects and read `scheduler.py`.

## Follow-ups

- [ ] DST-row count: not measured. This environment has no `DATABASE_URL`, no Postgres listener, no Docker, and no dump or staging copy of `odds_line_snapshots`. Production was not queried. Run this read-only query on a copy or on staging, with Eason's OK before any production `SELECT`. Do not `UPDATE` or `DELETE`.

```sql
-- Old final cron: 23:35 UTC. During daylight time that is 7:35 PM ET.
-- 2026 daylight time starts 2026-03-08 07:00 UTC and ends 2026-11-01 06:00 UTC.
-- The evening of 2026-11-01 is already EST, so 23:35 UTC that night is
-- 6:35 PM ET and is a normal standard-time final. Leave it out.
-- snapshot_at is taken at the start of the run, so allow a few minutes past :35.
SELECT COUNT(*) AS row_count,
       COUNT(DISTINCT snapshot_at) AS distinct_runs,
       MIN(snapshot_at) AS first_at,
       MAX(snapshot_at) AS last_at
FROM odds_line_snapshots
WHERE snapshot_at >= TIMESTAMPTZ '2026-03-08 07:00:00+00'
  AND snapshot_at <  TIMESTAMPTZ '2026-11-01 06:00:00+00'
  AND EXTRACT(HOUR FROM snapshot_at AT TIME ZONE 'UTC') = 23
  AND EXTRACT(MINUTE FROM snapshot_at AT TIME ZONE 'UTC') BETWEEN 30 AND 45;
```

- [ ] Flagging proposal, after that count is known: do not delete the rows. When a reader treats `odds_line_snapshots` as a closing line, exclude captures whose `snapshot_at` matches the predicate above (7:35 PM ET on a daylight-time date). Those rows can be in-game prices. `misfire_grace_time` is 3600 seconds, so a late final can land after 23:45 UTC and this window will miss it; widen the predicate only if the log shows those late runs. Apply the same rule to `odds_snapshot_logs` if a log row is what picks the final capture. Ship the flag in a follow-up, not in this PR.

## Progress notes (for the docs PR)

- SPO-143: the three odds snapshot crons fire at 11:05, 17:05, and 18:35 America/New_York year-round. The scheduler default stays UTC. Daylight-time rows at about 23:35 UTC were not counted here; there is no staging copy.

---

**Ticket**: SPO-143
**Branch**: `feature/SPO-143-odds-cron-timezone`
**Task summary**: `docs/task-summaries/SPO-143-odds-cron-timezone.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges.
