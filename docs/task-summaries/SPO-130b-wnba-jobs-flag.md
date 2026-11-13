# SPO-130b — WNBA_JOBS_ENABLED scheduler flag

- Ticket: SPO-130b
- Branch: `feature/SPO-130b-wnba-jobs-flag` (from `origin/dev` `55750de`)

## Summary

`WNBA_JOBS_ENABLED` maps to `settings.wnba_jobs_enabled` and defaults to `True`. `SchedulerService.start()` registers the four WNBA jobs only when that value is true. False skips `wnba_daily_analysis_job`, `wnba_lineup_fetch_opening`, `wnba_lineup_fetch_active_window`, and `wnba_lineup_fetch_pre_tipoff`, and writes one info line. Unset and true both keep today's job-id list. NBA jobs and WNBA HTTP routes stay as they are.

## Changes

| Area | File | Change |
|---|---|---|
| Settings | `backend/app/settings.py` | `wnba_jobs_enabled: bool = True` (env `WNBA_JOBS_ENABLED`). |
| Scheduler | `backend/app/services/scheduler.py` | The WNBA daily job and the three WNBA lineup jobs sit inside `if settings.wnba_jobs_enabled`. The false branch logs once. |
| Tests | `backend/tests/test_spo130b_wnba_jobs_flag.py` | Snapshot of today's ids. True and unset match it. False keeps that list with every `wnba*` id removed, and expects the one info line. The stand-in scheduler stores ids and does not fire triggers. `test_compose_passes_wnba_jobs_enabled_to_the_backend` checks the compose line below. |
| Env example | `env.example` | `WNBA_JOBS_ENABLED=true`. Comment lists the accepted spellings (`true/false/1/0/yes/no/on/off`) and the compose passthrough. There is no `backend/.env.example` in this tree. |
| Compose | `docker-compose.yml` | Backend `environment` passes `WNBA_JOBS_ENABLED=${WNBA_JOBS_ENABLED:-true}`. |
| Docs | `docs/task-summaries/SPO-130b-wnba-jobs-flag.md` | This file. |

## Why

SPO-138 has to pause WNBA jobs so a wipe is not refilled. The default stays true so a process that does not set the variable still registers the same jobs as today. The four registrations are the only `add_job` calls whose ids start with `wnba`. NBA registrations stay outside the condition.

## Blast radius

`add_job` exists only in `backend/app/services/scheduler.py`. `backend/app/main.py` starts the process by calling `scheduler_service.start()`, so that startup path is covered. Root `docker-compose.yml` passes `WNBA_JOBS_ENABLED=${WNBA_JOBS_ENABLED:-true}` into the backend service. The compose file lists environment names explicitly and has no `env_file`, and `.dockerignore` does not ship the repo `.env` into the image, so a name missing from that list never reaches the container. `:-true` keeps an unset variable from arriving as an empty string. `deploy/docker-compose.prod.yml` is not in this tree.

The flag is read only in `SchedulerService.start()`. These request paths still run when the flag is false:

| Call site | What still happens |
|---|---|
| `GET /api/wnba/lineups` | A cache miss calls `wnba_lineup_service.fetch_and_store`, which upserts Postgres. A stale cache calls `_trigger_background_refresh`, which calls `fetch_and_store` too. The `/wnba` page requests this route. |
| `GET /api/wnba/daily-picks` | A cache miss calls `run_daily_analysis(league="wnba")`, which calls the Odds API and writes Redis. The `/wnba` page requests this route. |
| `POST /api/wnba/daily-picks/trigger` | Calls `run_daily_analysis(league="wnba")` on the request. |
| `POST /api/wnba/lineups/refresh` | Calls `wnba_lineup_service.fetch_and_store` on the request. |
| `GET /api/wnba/lineups/{team}`, `DELETE /api/wnba/daily-picks/cache` | Team read, and a cache delete. |
| `odds_hot_key_prewarm` | An NBA-named job. A WNBA odds key read in the last 5 minutes can be refreshed into Redis. It does not write Postgres. |
| `_run_wnba_daily_analysis_job`, `_run_wnba_lineup_fetch_job` | Handlers remain. Tests call them directly. With the flag false they are not registered. |

This PR leaves those routes in place. The pause is the four scheduler registrations. There is no SPO-138 runbook in the tree. During that wipe, do not serve `/wnba` (those two GETs must not miss cache) and do not call the two POSTs.

The static startup banner still prints `Daily Analysis (WNBA): Daily UTC 12:00` when the flag is false. The `📌` lines come from `get_jobs()` and listed no WNBA id on the proof run. The info line is the skip signal.

## Tests

```
cd backend && REDIS_URL=redis://localhost:6379 \
  DATABASE_URL=postgresql://novig:novig@localhost:5432/novig_nba \
  ODDS_API_KEY=test-key OPENAI_API_KEY=test-key \
  pytest --tb=line -q
```

After the compose passthrough: `1605 passed, 28 skipped, 7 xfailed, 5 warnings in 80.25s`. The run before that line was `1604 passed, 28 skipped, 7 xfailed, 5 warnings in 77.09s`.

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

- SPO-138 wipe, until a runbook exists: with the flag false, do not serve `/wnba`. `GET /api/wnba/lineups` on a cache miss upserts lineup rows, and a stale cache refreshes in the background. `GET /api/wnba/daily-picks` on a cache miss calls the Odds API and writes Redis. Do not call `POST /api/wnba/daily-picks/trigger` or `POST /api/wnba/lineups/refresh`.
- `odds_hot_key_prewarm` can still refresh a recently read WNBA odds key into Redis. It does not write Postgres.
- After #64, add `WNBA_JOBS_ENABLED` to the optional SSM list and the prod compose comment (plan section 6).
- The hardcoded WNBA sentence in the startup banner still prints when the jobs are skipped.
- Accepted flag spellings are `true/false/1/0/yes/no/on/off`. An empty string, leading space, or any other word raises `ValidationError` and the process does not start. That matches `database_required`.
