# SPO-132c — fix migrate verify and add --verify-only

- Ticket: SPO-132c
- Branch: `feature/SPO-132c-migrate-verify-fix` (from `origin/dev`)
- Base: `dev`

## Summary

`scripts/db_migrate_to_rds.sh` compared row counts with `psql -c` and `:'tbl'` / `:'seq'`. psql does not substitute those variables inside `-c`, so verify died with `syntax error at or near ":"` after a successful restore. The same queries now go to psql on stdin, with `-v` still binding the name. `--verify-only` repeats that comparison and does not dump or restore.

## Changes

| Area | File | Change |
|---|---|---|
| Migrate | `scripts/db_migrate_to_rds.sh` | Verify SQL that binds `:'tbl'` or `:'seq'` is written to psql stdin. `--verify-only` skips `pg_dump`, `pg_restore`, and the pg_restore 16 gate. URL, sslmode, and client-mode checks stay. A mismatch still exits 1. URLs and passwords are still not printed. |
| Tests | `backend/tests/test_spo132c_migrate_verify.py` | Real Postgres 16. Two scratch databases, a quoted table name, a serial column, and a sequence. Identical data exits 0. A changed row count exits non-zero and prints `MISMATCH`. Output has no password or URL. Scratch databases are dropped. Skips only when psql is missing or Postgres is unreachable. |
| Tests | `backend/tests/test_spo132_rds_s3.py` | Fake `psql` and fake `docker` read SQL from stdin when `-c` is absent. `--verify-only` with a v17 fake client does not dump and does not refuse. |
| CI | `.github/workflows/ci.yml` | Backend tests install `postgresql-client` so the real Postgres test runs on the runner. |
| Docs | `docs/deployment/aws.md`, `docs/deployment/aws-steps-zh-TW.md` | `--verify-only`, including the note to re-run it when verify failed after restore. |

## Why

The restore had already finished, so running the whole script again would dump and restore into a database that is no longer empty. `--verify-only` is the second run. stdin is the smallest change that makes `:'var'` work: `-c` never interpolates it, and splicing the table name into the SQL string would drop `quote_ident`. `run_psql` already passes `-i` for `docker exec` and `docker run`, and the host client inherits the pipe, so all three modes receive stdin.

## Tests / Verification

- Reproduce, before the fix, against Postgres 16: `ERROR: syntax error at or near ":"` / `LINE 1: SELECT quote_ident(:'tbl')`. Dump and restore had already succeeded. No URL or password in the output.
- After the fix, one normal run (dump, restore, verify) and one `--verify-only` against two scratch `postgres:16` containers. Both exit 0. Output is in the PR.
- Backend pytest: `cd backend && /tmp/nba-venv/bin/python -m pytest --tb=line -q` → 1314 passed, 24 skipped, 6 xfailed, 0 failed. The new test ran (it was not skipped): identical data exited 0, then a deleted row exited non-zero with `Game Log|count|2|1|MISMATCH`.
- Frontend: not touched.
- Integration test: SKIPPED. No AWS call. The new test uses the local Postgres, not a mock of an external API.
- Fabrication scan: PASS. No hand-typed external API body.

## Follow-ups

- [ ] Host-mode `pg_restore` is still invoked without `--dbname`. That path is unchanged. The default client remains `docker exec`.
