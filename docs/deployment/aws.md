# AWS deployment (RDS PostgreSQL 16 + S3)

Sports Lab keeps Redis local. PostgreSQL and the raw Ball Don't Lie files move to AWS. Terraform for the resources is in `infra/aws/`. Eason runs `terraform apply`. This repository does not call AWS.

Placeholders only in `env.example` and `.env.example` (same template). Never commit `.env`, `terraform.tfvars`, or `terraform.tfstate`.

## Environment variables

| Variable | Who reads it | Value |
|---|---|---|
| `DATABASE_URL` | Backend, and `scripts/pg_dump_to_s3.sh` if `RDS_DATABASE_URL` is unset | App role DSN. SSL is part of the URL. |
| `DATABASE_REQUIRED` | Backend startup | `false` for local tests and dev without Postgres. **Set `true` in production** so a bad URL or a blocked IP stops the process instead of serving with an empty pool. |
| `AWS_ACCESS_KEY_ID` | `scripts/sync_raw_to_s3.sh`, `scripts/pg_dump_to_s3.sh` | Access key of the IAM user `sportslab-runtime`. Not an admin key. |
| `AWS_SECRET_ACCESS_KEY` | Same scripts | Secret for that key. |
| `AWS_REGION` | Same scripts | `us-east-2` unless the instance was created in another region. |
| `S3_BUCKET` | Same scripts | Bucket name from `terraform output bucket_name`. |
| `LOCAL_DATABASE_URL` | `scripts/db_migrate_to_rds.sh` only | Current local DSN. The API does not read this. |
| `RDS_DATABASE_URL` | `scripts/db_migrate_to_rds.sh`, and the daily dump if set | RDS DSN. Use the master user for the one-time restore. Use `sportslab_app` for the daily dump once that role owns the tables. |

`DATABASE_URL` for the backend:

```text
postgresql://sportslab_app:REPLACE_ME@REPLACE_ME.rds.amazonaws.com:5432/novig_nba?sslmode=verify-full&sslrootcert=/app/certs/global-bundle.pem
```

`sslmode=require` is the minimum. `verify-full` checks the server name against the RDS CA bundle. asyncpg 0.30 reads `sslmode` and `sslrootcert` from that query string, and also honors `PGSSLROOTCERT`. No extra SSL setting is appended in code. Download the public bundle once (it is not a secret):

```bash
curl -fsSL -o /app/certs/global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
```

Mount that path into the backend container, or copy it in the image. `rds.force_ssl=1` on the instance rejects a non-TLS connection.

`docker-compose.yml` still defaults `DATABASE_URL` to the local `postgres` service and `DATABASE_REQUIRED` to `false`. Export both before `docker compose up` when you want the container on RDS.

Startup prints the database URL with the password replaced by `***`. A failed `db.init()` is logged the same way. With `DATABASE_REQUIRED=false` the process keeps running and projections fall back to Redis. With `DATABASE_REQUIRED=true` startup raises.

## App role

After the instance is up, connect as `sportslab_admin` (password from Secrets Manager, ARN in `terraform output master_user_secret_arn`) and create the role the API will use. Replace the password locally; do not commit it.

```sql
CREATE ROLE sportslab_app LOGIN PASSWORD 'REPLACE_ME';
GRANT CONNECT ON DATABASE novig_nba TO sportslab_app;
GRANT USAGE, CREATE ON SCHEMA public TO sportslab_app;
```

On PostgreSQL 15+ the `public` schema does not allow `CREATE` for every role. The grant above is what lets `SCHEMA_SQL` create the six tables as `sportslab_app`, so that role owns them.

## Cutover

1. Eason creates the account, the $25 budget, and the identities. Apply `infra/aws` (or the console fallback in `infra/aws/README.md`).
2. Enter `DATABASE_URL`, the runtime AWS keys, and `AWS_REGION` through the masked secret form. From the box: `psql "$DATABASE_URL" -c 'select version()'`.
3. Create `sportslab_app`. Point a throwaway `DATABASE_URL` at that role and start the backend once against the empty database. Confirm the six tables and the SPO-117 key (`\d odds_line_snapshots`). Stop that process before the restore.
4. Merge the app change to `dev`, then to `master`, so production has masked logs and `DATABASE_REQUIRED`.
5. Pick a quiet window with no scheduler job in the next 30 minutes (08:00–09:00 UTC is the example). Stop the local backend. The scheduler runs in that process; stopping it freezes writes so the counts match.
6. Restore into an **empty** database. `scripts/db_migrate_to_rds.sh` does not pass `--clean`. If step 3 already created tables, drop and recreate `novig_nba` (or drop those tables) before the restore. Run:

```bash
LOCAL_DATABASE_URL='...' RDS_DATABASE_URL='...' ./scripts/db_migrate_to_rds.sh
```

`pg_restore` must be major version 16. A v17 client emits `SET transaction_timeout`, which PostgreSQL 16 rejects, and the script exits before the restore. The script prints `name|metric|local|rds|status` for each public table's row count and `max(id)`, and for each sequence's `last_value`. Any mismatch exits non-zero. It does not print either URL.

7. Set the backend's `DATABASE_URL` to the `sportslab_app` RDS URL and `DATABASE_REQUIRED=true`. Start it. Logs show the masked RDS host, then "tables are ready". The next scheduled snapshot should write rows on RDS.
8. Run `scripts/sync_raw_to_s3.sh` once, then daily `scripts/pg_dump_to_s3.sh` at 10:00 UTC (04:00 CT, before the 12:00 UTC analysis). The sync has no `--delete`. The dump object is `pg-dumps/<UTC date>.dump` and the bucket lifecycle expires current dumps after 90 days. Keep the local `pg-data` volume for two weeks.

The box has to be in `allowed_cidrs` for steps 2, 6, and 8. The backend host's egress address has to be in that list before step 7.

## Rollback

- Before step 7 succeeds: nothing in production changed. Start the local backend with the old `DATABASE_URL`.
- After cutover: set `DATABASE_URL` back to the local database and restart. Rows written to RDS after the cutover are not in the local volume unless you dump RDS and restore locally (same script, URLs swapped, and a PostgreSQL 16 `pg_restore`). Keep the local volume until RDS has run cleanly for two weeks.

## Scripts

| Script | Required environment | What it refuses to do |
|---|---|---|
| `scripts/db_migrate_to_rds.sh` | `LOCAL_DATABASE_URL`, `RDS_DATABASE_URL` | Print URLs or passwords. Run `pg_restore` when its major version is not 16 (override: `ALLOW_PG_RESTORE_MISMATCH=1`). Restore when the two URLs are identical. |
| `scripts/sync_raw_to_s3.sh` | `S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | `--delete`. Paths default to `/workspace/bdl-cache`, `/workspace/bdl-archive`, `/workspace/bdl-eval/samples` and can be overridden with `BDL_CACHE_DIR`, `BDL_ARCHIVE_DIR`, `BDL_SAMPLES_DIR`. |
| `scripts/pg_dump_to_s3.sh` | Those AWS variables plus `RDS_DATABASE_URL` or `DATABASE_URL` | Print the database URL. `DUMP_DATE=YYYY-MM-DD` overrides the UTC date in the object key. |

If a required variable is missing, the script prints help and a dry-run line and exits 2. It does not call `pg_dump`, `pg_restore`, or `aws`.
