# SPO-130b — WNBA_JOBS_ENABLED scheduler flag

- Ticket: SPO-130b
- Branch: `feature/SPO-130b-wnba-jobs-flag` (from `origin/dev` `55750de`)

## Summary

`WNBA_JOBS_ENABLED` maps to `settings.wnba_jobs_enabled` and defaults to `True`. `SchedulerService.start()` registers the four WNBA jobs only when that value is true. False skips those jobs, logs one info line, and the startup banner says the WNBA daily job is not registered. The writes themselves are guarded in `fetch_and_store` and `run_daily_analysis`: with the flag false, a WNBA lineup fetch does not scrape or write Redis or Postgres, and a WNBA daily analysis does not call the Odds API or write Redis. A stored lineup slate or daily board is still returned. A cache miss returns an empty result. The two manual POSTs return 409. Unset and true keep today's NBA and WNBA behavior. Root `docker-compose.yml` passes `WNBA_JOBS_ENABLED=${WNBA_JOBS_ENABLED:-true}` into the backend container. No other compose file sets backend env.

## Changes

| Area | File | Change |
|---|---|---|
| Settings | `backend/app/settings.py` | `wnba_jobs_enabled: bool = True` (env `WNBA_JOBS_ENABLED`). |
| Scheduler | `backend/app/services/scheduler.py` | The four WNBA jobs sit inside `if settings.wnba_jobs_enabled`. The false branch logs once. The banner's WNBA line says the job is not registered when the flag is false. |
| Lineups | `backend/app/services/lineup_service.py` | `fetch_and_store` returns `{}` for WNBA when the flag is false, before the scrape and before Redis or Postgres. `get_lineups` returns a stored slate, or an empty slate on a miss, and does not call `fetch_and_store`. |
| Daily picks | `backend/app/services/daily_analysis.py` | After a cache hit, `run_daily_analysis(league="wnba")` returns an empty board when the flag is false. It does not call the Odds API and does not write Redis. |
| Routes | `backend/app/api/wnba.py` | `POST /api/wnba/daily-picks/trigger` and `POST /api/wnba/lineups/refresh` return 409 with `WNBA jobs are paused (WNBA_JOBS_ENABLED=false)`. |
| Prewarm | `backend/app/services/odds_gateway.py` | `prewarm_hot_keys` skips members whose sport is `basketball_wnba` when the flag is false. NBA members still refresh. |
| Tests | `backend/tests/test_spo130b_wnba_jobs_flag.py`, `backend/tests/test_spo130b_qa.py`, `backend/tests/test_odds_gateway.py` | Job-id snapshot, compose passthrough, QA parsing and NBA job shape, lineup read, write guards, and the two 409s. The QA xfails are removed. |
| Env example | `env.example` | `WNBA_JOBS_ENABLED=true`. Comment lists `true/false/1/0/yes/no/on/off` and the compose passthrough. There is no `backend/.env.example` in this tree. |
| Compose | `docker-compose.yml` | Backend `environment` passes `WNBA_JOBS_ENABLED=${WNBA_JOBS_ENABLED:-true}`. |
| Docs | `docs/task-summaries/SPO-130b-wnba-jobs-flag.md` | This file. |

## Why

SPO-138 has to pause WNBA jobs so a wipe is not refilled. The default stays true so a process that does not set the variable still registers the same jobs as today. The four registrations are the only `add_job` calls whose ids start with `wnba`. NBA registrations stay outside the condition.

## Blast radius

`add_job` for the four WNBA jobs is only in `SchedulerService.start()`. `main.py` calls that on startup. Root `docker-compose.yml` is the only compose file that sets backend env. It passes `WNBA_JOBS_ENABLED=${WNBA_JOBS_ENABLED:-true}`. The file lists names explicitly and has no `env_file`, and `.dockerignore` does not ship the repo `.env`, so a missing name never reaches the container. `:-true` keeps an unset name from arriving as an empty string. `deploy/docker-compose.prod.yml` is not in this tree.

With the flag false, the writes stop inside the services:

| Call site | What happens |
|---|---|
| `fetch_and_store` on the WNBA lineup service | Returns `{}` before the scrape, Redis, the Postgres upsert, and the fetch log. |
| `get_lineups` / `GET /api/wnba/lineups` and `GET /api/wnba/lineups/{team}` | Returns the stored slate. A miss returns an empty slate and does not call `fetch_and_store`. A stale slate is not refreshed in the background. |
| `run_daily_analysis(league="wnba")` / `GET /api/wnba/daily-picks` | Returns a stored board. A miss returns an empty board with `message` `WNBA jobs are paused (WNBA_JOBS_ENABLED=false)`. No Odds API call and no Redis write. |
| `POST /api/wnba/daily-picks/trigger` and `POST /api/wnba/lineups/refresh` | `409` with that same detail. The handlers are not called. |
| `DELETE /api/wnba/daily-picks/cache` | Still deletes `daily_picks:wnba:*`. |
| `odds_hot_key_prewarm` | Skips hot keys whose sport is `basketball_wnba`. NBA keys still refresh. |
| WNBA odds routes (`/events`, `/props/no-vig`, `/players/suggest`) | Still call the Odds API when a user requests them. They are not the prewarm job. |
| NBA jobs, NBA `fetch_and_store`, NBA `run_daily_analysis` | Unchanged at both flag values. |

The startup banner prints `Daily Analysis (WNBA): not registered (WNBA_JOBS_ENABLED is false)` when the flag is false, and the UTC 12:00 line when it is true. The `📌` list is `get_jobs()`.

## Tests

```
cd backend && REDIS_URL=redis://localhost:6379 \
  DATABASE_URL=postgresql://novig:novig@localhost:5432/novig_nba \
  ODDS_API_KEY=test-key OPENAI_API_KEY=test-key \
  pytest --tb=line -q
```

After the service guards: `1630 passed, 28 skipped, 7 xfailed, 5 warnings in 77.72s`. Against `acf4fa9` that is 26 more passes (`1604 passed, 28 skipped, 7 xfailed`). Skipped and xfailed counts are unchanged. The two QA xfails now pass.

Redis 7 and Postgres 16 were on localhost with the same URLs as CI. Docker is not installed here, so `REQUIRE_DOCKER_TESTS` was left unset and the real-docker verify test stayed in the skip count. `RUN_INTEGRATION` was unset. No live Odds API or BALLDONTLIE call.

One startup with `WNBA_JOBS_ENABLED=false` set before import (`wnba_jobs_enabled=False`):

```
INFO app.services.scheduler: WNBA_JOBS_ENABLED is false; skipping WNBA jobs: wnba_daily_analysis_job, wnba_lineup_fetch_opening, wnba_lineup_fetch_active_window, wnba_lineup_fetch_pre_tipoff
```

Job ids from that start (`get_jobs()`, next-run order). No id starts with `wnba`:

```
nba_injuries_startup_fill
lineup_fetch_active_window
odds_hot_key_prewarm
nba_injuries_refresh
lineup_fetch_pre_tipoff
daily_analysis_job
lineup_fetch_opening
csv_download_job
odds_snapshot_early
odds_snapshot_mid
odds_snapshot_final
```

`ruff check` on the three Python files with `--select E9,F63,F7,F82` passed.

## Follow-ups

- A user request to `GET /api/wnba/events`, `/props/no-vig`, or `/players/suggest` still calls the Odds API when the flag is false. The prewarm job does not.
- After #64, add `WNBA_JOBS_ENABLED` to the optional SSM list and the prod compose comment (plan section 6).
- Accepted flag spellings are `true/false/1/0/yes/no/on/off`. An empty string, leading space, or any other word raises `ValidationError` and the process does not start. That matches `database_required`.
