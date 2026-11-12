# SPO-132f — probe Postgres readiness over TCP

- Ticket: SPO-132f
- Branch: `feature/SPO-132f-pg-ready-tcp` (from `origin/dev` at `7b5c609`)
- Base: `dev`

## Summary

`test_verify_only_real_docker_exec_compares_every_table` could treat Postgres as ready while the official image was still restarting. The entrypoint starts a temporary init server that listens only on the Unix socket, stops it, then starts the real server. `_wait_postgres` ran `pg_isready -U novig -d novig` on that socket, so it could succeed against the temporary server. The next `docker exec ... psql` then failed with `No such file or directory` on `/var/run/postgresql/.s.PGSQL.5432`. Readiness now uses `pg_isready -h 127.0.0.1 -p 5432`. The temporary server does not answer on TCP. The same `-h 127.0.0.1` flag is on the Compose healthcheck and the CI service health command. `scripts/db_migrate_to_rds.sh` does not call `pg_isready`.

## Changes

| Area | File | Change |
|---|---|---|
| Tests | `backend/tests/test_spo132c_migrate_verify.py` | `_wait_postgres` probes `pg_isready -h 127.0.0.1 -p 5432 -U novig -d novig`. The loop is still 40 tries and `0.5` seconds. A fake `docker` on `PATH` reports ready for a socket-only `pg_isready` and not ready for `-h 127.0.0.1` until the third call. The helper returns only after that TCP probe succeeds, and raises when TCP stays down for the whole loop. |
| Compose | `docker-compose.yml` | The Postgres healthcheck command is `pg_isready -h 127.0.0.1 -U novig -d novig_nba`. No other line in the file changed. |
| CI | `.github/workflows/ci.yml` | The Postgres service `--health-cmd` is `pg_isready -h 127.0.0.1 -U novig -d novig_nba`. No other line in the file changed. |
| Docs | `docs/task-summaries/SPO-132f-pg-ready-tcp.md` | This summary. |

## Why

A socket-only `pg_isready` cannot tell the temporary init server from the real postmaster. TCP can: the init server never listens on `127.0.0.1`. Adding `-h 127.0.0.1` keeps the existing timeout and does not change the migrate script. `git grep -n pg_isready -- scripts` prints nothing, including `scripts/db_migrate_to_rds.sh`.

The regression test does not need Docker. The shim returns success for a socket probe immediately, so the old helper would return on the first call. It returns failure for TCP until call 3, so the new helper cannot return before TCP is ready. A second case never marks TCP ready. The helper raises `AssertionError` after 40 TCP failures even though a socket probe would have succeeded. `time.sleep` is replaced with a no-op in these two tests so the timeout case does not wait 20 seconds. The loop count is unchanged.

## Tests / Verification

- New tests, no Docker: `test_wait_postgres_does_not_return_until_tcp_is_ready` and `test_wait_postgres_raises_when_tcp_never_becomes_ready`. Both passed (`2 passed`).
- Real Docker loop: Docker is not installed on this machine (`docker` is not on `PATH`). `test_verify_only_real_docker_exec_compares_every_table` was skipped. The 10-run loop was not run.
- Backend pytest: `cd backend && /tmp/nba-venv/bin/python -m pytest --tb=line -q` → 1323 passed, 33 skipped, 6 xfailed, 0 failed.
- Frontend: not touched.
- Integration test: SKIPPED. No live external API. `psql` is also absent here, so the host-mode Postgres cases in this file skipped.
- Fabrication scan: PASS. No hand-typed external API body.

## Follow-ups

- [ ] Host-mode `pg_restore` is still invoked without `--dbname`. That path is unchanged. The default client remains `docker exec`.
