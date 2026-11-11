# SPO-132e — migrate verify fails closed on empty schemas

- Ticket: SPO-132e
- Branch: `feature/SPO-132e-verify-fail-closed` (from `origin/feature/SPO-132d-verify-loop-stdin` at `4dbf02f`)
- Base: `dev`
- Stacks on #70. After #70 squash-merges, update this branch with `git merge origin/dev`.

## Summary

`scripts/db_migrate_to_rds.sh --verify-only` printed `ok:` and exited 0 when both sides listed zero public tables. That is the wrong database, the wrong schema, or an empty target, and the cutover gate has to fail closed. Either side listing zero public tables now exits 1. The stderr line is the two counts. It does not include a URL or a password.

The sequence loop now has the same count check the table loop has. The number compared must equal the number listed on the local side and the number listed on the RDS side. Zero sequences is a match only when both sides list zero, because a database can legitimately have no sequences.

## Changes

| Area | File | Change |
|---|---|---|
| Migrate | `scripts/db_migrate_to_rds.sh` | Exit 1 when either side lists zero public tables. Count the sequences actually compared and require that count to equal both listed counts. Zero sequences stays success only when both counts are zero. |
| Tests | `backend/tests/test_spo132d_qa_verify_modes.py` | QA's mode matrix, applied as its own commit. The empty-schema case is a normal passing test. One-sided empty schemas fail. Tables with no sequences still pass. A sequence present on only one side fails the count check. |
| Tests | `backend/tests/test_spo132c_migrate_verify.py` | Readiness uses `pg_isready -h 127.0.0.1`. Every docker subprocess has a timeout. `REQUIRE_DOCKER_TESTS=1` fails the test when docker cannot run; otherwise it still skips. The same two Postgres 16 containers cover docker-exec and docker-run, match and mismatch. |
| Tests | `backend/tests/test_spo132_rds_s3.py` | `--help` must mention the zero-table failure and the zero-sequence rule. |
| CI | `.github/workflows/ci.yml` | Backend Tests `timeout-minutes: 15`. `REQUIRE_DOCKER_TESTS=1`. The Postgres service health check uses `pg_isready -h 127.0.0.1`. |
| Compose | `docker-compose.yml` | The Postgres health check uses `pg_isready -h 127.0.0.1`. |
| Docs | `docs/deployment/aws.md`, `docs/deployment/aws-steps-zh-TW.md` | The verify gate fails when either side lists zero public tables. |
| Docs | `docs/task-summaries/SPO-132e-verify-fail-closed.md` | This summary. |

## Why

A verify that succeeds on an empty public schema will bless a cutover onto the wrong database. Failing before the report, with only the two counts, keeps the URL and the password out of the error and makes the miss obvious. Checking "either side" covers a source that has tables and a target that does not, which is the same class of mistake.

Sequences are different. A table without a `serial` column has no sequence, and that database is valid. The count check still fails a short read and a one-sided list, which is the hole the table check was added to close. The success case is both counts equal to each other, including both zero.

`pg_isready` without `-h` uses the unix socket. Postgres 16 opens that socket for the temporary server it runs during init, so a readiness probe can succeed before the real postmaster is listening. `-h 127.0.0.1` waits for TCP. The same probe is used in the docker test, the compose health check, and the CI service health check.

Recent Backend Tests jobs finished in 75s, 90s, and 79s (runs 43102716772, 43106159296, 43108025796). The job previously had no `timeout-minutes`, so a hang waited until the platform default of 360 minutes. Fifteen minutes is about ten times the longest of those runs. It leaves room for the `postgres:16` pull and the docker-run pass. Subprocess timeouts in the docker test are 120 seconds (15 seconds for the readiness probe, which retries). On this machine the combined docker-exec and docker-run test, match and mismatch, finished in 98 seconds, so the extra mode fits in that job limit.

## Tests / Verification

Two empty `postgres:16` containers, `PG_CLIENT=docker-exec`, exit 1. stdout was empty. stderr:

```
error: local lists 0 public tables and rds lists 0 public tables.
```

The same containers after the same rows were loaded on both sides, exit 0:

```
name|metric|local|rds|status
alpha_table|count|1|1|OK
alpha_table|max_id|1|1|OK
beta_table|count|2|2|OK
beta_table|max_id|2|2|OK
alpha_table_id_seq|last_value|1|1|OK
beta_table_id_seq|last_value|2|2|OK
extra_seq|last_value|5|5|OK
ok: public table counts, max(id), and sequence last_value match.
```

No URL or password in either run.

Before the fix, QA's `test_empty_public_schema_on_both_sides_is_not_ok` was a strict xfail (`1 xfailed`). It is a passing test now.

- Backend pytest: `cd backend && /tmp/nba-venv/bin/python -m pytest --tb=line -q -rs` with `REQUIRE_DOCKER_TESTS=1` → 1346 passed, 24 skipped, 6 xfailed, 0 failed, in 156.59s. The 24 skips are live API tests. `test_verify_only_real_docker_compares_every_table` ran (docker-exec and docker-run). It was not skipped.
- The previous count on #70 was 1317 passed, 24 skipped, 6 xfailed. This branch adds 29 passing tests.
- Frontend: not touched.
- Integration test: SKIPPED. No AWS call.
- Fabrication scan: PASS. No hand-typed external API body.
- `ruff check . --select E9,F63,F7,F82` and `python -m compileall -q .` in `backend/`: passed.

## Follow-ups

- [ ] Host-mode `pg_restore` is still invoked without `--dbname`. That path is unchanged. The default client remains `docker exec`.
