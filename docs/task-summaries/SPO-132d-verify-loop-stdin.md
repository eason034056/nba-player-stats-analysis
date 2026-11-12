# SPO-132d — compare every table in migrate verify under docker modes

- Ticket: SPO-132d
- Branch: `feature/SPO-132d-verify-loop-stdin` (from `origin/dev` at `8b8bbdc`)
- Base: `dev`

## Summary

`scripts/db_migrate_to_rds.sh --verify-only` in docker-exec and docker-run compared only the first public table and then printed `ok:`. `docker exec -i` and `docker run -i` read the shell's stdin, so a `-c` query inside the table loop consumed the rest of the here-doc. A mismatch in a later table still exited 0. Host mode was already fine, because `psql -c` does not read stdin. The name lists now arrive on fd 3, every `-c` call uses `/dev/null` for stdin, and the script exits 1 when the number of tables compared is not the number listed on the local side or the RDS side.

## Changes

| Area | File | Change |
|---|---|---|
| Migrate | `scripts/db_migrate_to_rds.sh` | Table and sequence loops read on fd 3. `run_psql` sends stdin from `/dev/null` when the arguments include `-c`. `run_psql_stdin` still pipes the SQL. After the loops, the compared table count must equal both listed counts or the script exits 1. |
| Tests | `backend/tests/test_spo132_rds_s3.py` | The fake `docker` drains stdin on a `-c` query, the way `docker exec -i` does, and lists two public tables. |
| Tests | `backend/tests/test_spo132c_migrate_verify.py` | Docker-exec against Postgres, with the mismatch only on the second table, must exit non-zero and print that line. A real `docker exec` into Postgres 16 covers three identical tables and then the same second-table mismatch. It skips only when `docker` cannot run. Host mode still runs. |
| Docs | `docs/task-summaries/SPO-132d-verify-loop-stdin.md` | This summary. |

## Why

The smallest fix that stays correct is to stop sharing stdin between the name list and the docker client. fd 3 keeps the list even if a later command forgets `/dev/null`. `/dev/null` on `-c` keeps a future loop that still uses stdin from being eaten. `run_psql_stdin` cannot use `/dev/null`: psql only substitutes `:'tbl'` and `:'seq'` when the SQL is on stdin. Other loops in this script parse arguments or percent-decoding and do not read a name list, so they were left as they are. Counting the tables actually compared makes a short read fail even when the tables that were reached happened to match.

## Tests / Verification

Before the fix, two `postgres:16` containers, docker-exec, mismatch only in `second_table`: exit 0, and the report contained `first_table` plus `ok:`. `second_table` and `third_table` were absent.

After the fix, same containers:

Identical data, exit 0:

```
name|metric|local|rds|status
first_table|count|1|1|OK
first_table|max_id|1|1|OK
second_table|count|2|2|OK
second_table|max_id|2|2|OK
third_table|count|1|1|OK
third_table|max_id|1|1|OK
extra_seq|last_value|5|5|OK
first_table_id_seq|last_value|1|1|OK
second_table_id_seq|last_value|2|2|OK
third_table_id_seq|last_value|1|1|OK
ok: public table counts, max(id), and sequence last_value match.
```

Mismatch only in `second_table`, exit 1:

```
name|metric|local|rds|status
first_table|count|1|1|OK
first_table|max_id|1|1|OK
second_table|count|2|1|MISMATCH
second_table|max_id|2|1|MISMATCH
third_table|count|1|1|OK
third_table|max_id|1|1|OK
extra_seq|last_value|5|5|OK
first_table_id_seq|last_value|1|1|OK
second_table_id_seq|last_value|2|2|OK
third_table_id_seq|last_value|1|1|OK
error: at least one public table or sequence does not match.
```

No URL or password in that output.

- Backend pytest: `cd backend && /tmp/nba-venv/bin/python -m pytest --tb=line -q` → 1317 passed, 24 skipped, 6 xfailed, 0 failed. The new docker-exec cases ran (they were not skipped).
- Frontend: not touched.
- Integration test: SKIPPED. No AWS call. The new tests use local Postgres, not a mock of an external API.
- Fabrication scan: PASS. No hand-typed external API body.

## Follow-ups

- [ ] Host-mode `pg_restore` is still invoked without `--dbname`. That path is unchanged. The default client remains `docker exec`.
