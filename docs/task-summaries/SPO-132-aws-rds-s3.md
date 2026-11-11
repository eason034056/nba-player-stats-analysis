# SPO-132 — AWS RDS PostgreSQL 16 and S3

- Ticket: SPO-132
- Branch: `feature/SPO-132-aws-rds-s3` (from `origin/dev` at `4bfb2ec`)
- Base: `dev`

## Summary

PostgreSQL moves to a Single-AZ RDS 16 instance and the raw files move to a private S3 bucket. Terraform in `infra/aws/` describes both. Nothing in this change calls AWS, and no credentials are committed. The backend masks the database password before printing or logging it. `DATABASE_REQUIRED` stays false for local tests and dev, and production sets it true so a failed database init stops the process. SSL stays in the DSN; asyncpg 0.30 already reads `sslmode` and `sslrootcert`.

## Changes

| Area | File | Change |
|---|---|---|
| Terraform | `infra/aws/*.tf`, `terraform.tfvars.example`, `.gitignore`, `.terraform.lock.hcl` | RDS PostgreSQL 16.x on `db.t4g.micro`, gp3 20 GB, Single-AZ, backups 7 days, storage encrypted with `aws/rds`, `rds.force_ssl=1`, deletion protection, RDS-managed master password. Region default `us-east-2`. `allowed_cidrs` is `list(string)` with no default; every entry must be a host CIDR (`/32` or narrower) and `0.0.0.0/0` / `::/0` are rejected. The example lists box `184.193.214.44/32` and placeholder `203.0.113.10/32` (`# mac-home`). S3 bucket with Block Public Access, versioning, SSE-S3, TLS-only policy, 128 KB lifecycle, and prefixes `bdl-raw/`, `bdl-archive/`, `bdl-samples/`, `pg-dumps/`. `pg-dumps/` current objects expire after 90 days. Runtime IAM user can Get, Put, and List those prefixes and cannot delete. Outputs are the endpoint, the secret ARN, and the bucket name. |
| Runbook | `infra/aws/README.md` | `terraform init`, `plan`, and `apply` for Eason on his Mac. The account already exists. The provisioner IAM JSON is a reference list only; no provisioner key is created. |
| Migrate | `scripts/db_migrate_to_rds.sh` | Default `docker exec no-vig-nba-postgres pg_dump`. Fallback `docker run --rm postgres:16`. Host binaries remain available with `PG_CLIENT=host`. Adds `sslmode=require` on the RDS URL when `sslmode` is absent. Compares public row counts, `max(id)`, and sequence `last_value`. Refuses a `pg_restore` whose major version is not 16. Never prints URLs or passwords. |
| Home IP | `scripts/aws_update_my_ip.sh` | Reads the public IP with curl, rewrites the gitignored `# mac-home` line, keeps `184.193.214.44/32`, and prints `terraform apply`. Does not call AWS unless `--apply` is passed. |
| Sync | `scripts/sync_raw_to_s3.sh` | `aws s3 sync` of the three local trees to the three prefixes. Paths default to `/workspace/bdl-cache`, `/workspace/bdl-archive`, and `/workspace/bdl-eval/samples`. No `--delete`. |
| Dump | `scripts/pg_dump_to_s3.sh` | Daily `pg_dump -Fc` to `pg-dumps/<UTC date>.dump`. States that the bucket lifecycle keeps each current dump for 90 days. |
| Tests | `backend/tests/test_spo132_rds_s3.py` | Mask helper, SSL DSN passthrough, `DATABASE_REQUIRED` startup, and the scripts run with missing env or fake binaries. |
| Startup | `backend/app/dsn.py`, `backend/app/main.py`, `backend/app/services/db.py`, `backend/app/settings.py` | `mask_database_url` replaces the password with `***`. Init failures are logged without the password. `DATABASE_REQUIRED` (default false) raises from the lifespan when the pool does not open. |
| Compose | `docker-compose.yml` | `DATABASE_URL` and `DATABASE_REQUIRED` can come from the environment. The local Postgres URL and `false` remain the defaults. |
| Docs | `docs/deployment/aws.md`, `docs/deployment/aws-steps-zh-TW.md`, `docs/decisions/spo-132-aws-rds-s3/decision_20261111_rds-and-s3.md`, `env.example`, `.env.example` | English env vars, cutover, and rollback. Separate Traditional Chinese Mac steps. The two docs link to each other. Placeholders only. |
| Ignore | `.gitignore`, `infra/aws/.gitignore` | Local Terraform state and `*.tfvars`. The example tfvars file stays tracked. |

## Why

The startup print included the password, and a failed `init()` only set the pool to `None`. A remote database that rejects the box IP would look like a healthy API with no persistence. Production has to opt in to a hard failure (`DATABASE_REQUIRED=true`) because the test suite and local compose still start without Postgres.

asyncpg 0.30 already applies `sslmode` and `sslrootcert` from the DSN query string. Copying those into a separate setting would risk two different values. `create_pool` receives `settings.database_url` unchanged.

The box has `pg_restore` 17. That client writes `SET transaction_timeout`, which PostgreSQL 16 rejects, so the migration script stops before restore unless `ALLOW_PG_RESTORE_MISMATCH=1`. The daily dump can still use a v17 client, because that path only dumps.

Single-AZ, a public endpoint with an allowlist, SSE-S3, and the AWS-managed RDS key are the cost and operations choices in the plan. The runtime policy has no delete, and Terraform does not create access keys, so a key cannot land in state. `0.0.0.0/0` is rejected in `variable` validation, not only in a comment.

## Tests / Verification

- Backend pytest: `cd backend && /tmp/nba-venv/bin/python -m pytest -q --tb=line` → 1229 passed, 26 skipped, 6 xfailed, 0 failed.
- Frontend: not touched.
- Integration test: SKIPPED. No AWS account, no `RUN_INTEGRATION`. Script tests use fake `pg_dump`, `pg_restore`, `psql`, `docker`, `curl`, and `aws` binaries.
- Fabrication scan: PASS. This change does not mock an external odds or stats API and does not add a hand-typed response body.
- Terraform: `terraform fmt -check -recursive` clean. `terraform init -backend=false` uses hashicorp/aws v5.100.0. `terraform validate` succeeded. `terraform console` rejects `0.0.0.0/0`, `::/0`, and `10.1.2.0/24`, and accepts `184.193.214.44/32` plus `203.0.113.10/32`. It does not call AWS. `terraform plan` and `terraform apply` were not run.

## Follow-ups

- [ ] Eason checks the existing account's plan and bill, sets the $25 budget alarm, then applies `infra/aws` himself. Confirm the current PostgreSQL 16 minor with `describe-db-engine-versions`. Default `engine_version` is `16.15`.
- [x] The backend runs on the home Mac. It has no static IP. `allowed_cidrs` is box `184.193.214.44/32` plus the Mac `/32` from `scripts/aws_update_my_ip.sh`.
- [x] No provisioner key is issued. Eason uses `aws configure` on the Mac.
- [x] Daily `pg-dumps/` objects are kept 90 days (`pg_dump_retention_days`).
- [ ] Download the RDS CA bundle to the path in `sslrootcert`. It is not committed.
- [ ] Create `sportslab_app` with SQL after apply. Terraform does not create that role.
- [ ] Wire `sync_raw_to_s3.sh` and `pg_dump_to_s3.sh` to a schedule after the first successful sync and dump. The scripts are not cron yet.
- [ ] Local `pg-data` stays for two weeks after cutover. Row counts of the live database were not available from this environment.
