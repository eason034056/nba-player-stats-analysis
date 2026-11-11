# SPO-132 — AWS RDS PostgreSQL 16 and S3

- Ticket: SPO-132
- Branch: `feature/SPO-132-aws-rds-s3` (from `origin/dev` at `4bfb2ec`)
- Base: `dev`

## Summary

PostgreSQL moves to a Single-AZ RDS 16 instance and the raw files move to a private S3 bucket. Terraform in `infra/aws/` describes both. Nothing in this change calls AWS, and no credentials are committed. The backend masks the database password before printing or logging it. `DATABASE_REQUIRED` stays false for local tests and dev, and production sets it true so a failed database init stops the process. SSL stays in the DSN; asyncpg 0.30 already reads `sslmode` and `sslrootcert`.

## Changes

| Area | File | Change |
|---|---|---|
| Terraform | `infra/aws/*.tf`, `terraform.tfvars.example`, `.gitignore`, `.terraform.lock.hcl` | RDS PostgreSQL 16.x on `db.t4g.micro`, gp3 20 GB, Single-AZ, backups 7 days, storage encrypted with `aws/rds`, `rds.force_ssl=1`, deletion protection, RDS-managed master password. Security group opens 5432 only from `allowed_cidrs` and rejects `0.0.0.0/0`. S3 bucket with Block Public Access, versioning, SSE-S3, TLS-only policy, 128 KB lifecycle, and prefixes `bdl-raw/`, `bdl-archive/`, `bdl-samples/`, `pg-dumps/`. Runtime IAM user can Get, Put, and List those prefixes and cannot delete. Region, CIDRs, bucket name, instance class, storage, retention, project, and tags are variables. Outputs are the endpoint, the secret ARN, and the bucket name. |
| Runbook | `infra/aws/README.md` | `terraform init`, `plan`, and `apply` for Eason, the console fallback, and the provisioner IAM policy. |
| Migrate | `scripts/db_migrate_to_rds.sh` | `pg_dump -Fc` from `LOCAL_DATABASE_URL`, `pg_restore --no-owner` to `RDS_DATABASE_URL`, then compare public row counts, `max(id)`, and sequence `last_value`. Exits non-zero on a mismatch. Refuses a `pg_restore` whose major version is not 16. Never prints URLs or passwords. |
| Sync | `scripts/sync_raw_to_s3.sh` | `aws s3 sync` of the three local trees to the three prefixes. Paths default to `/workspace/bdl-cache`, `/workspace/bdl-archive`, and `/workspace/bdl-eval/samples`. No `--delete`. |
| Dump | `scripts/pg_dump_to_s3.sh` | Daily `pg_dump -Fc` to `pg-dumps/<UTC date>.dump`. |
| Tests | `backend/tests/test_spo132_rds_s3.py` | Mask helper, SSL DSN passthrough, `DATABASE_REQUIRED` startup, and the scripts run with missing env or fake binaries. |
| Startup | `backend/app/dsn.py`, `backend/app/main.py`, `backend/app/services/db.py`, `backend/app/settings.py` | `mask_database_url` replaces the password with `***`. Init failures are logged without the password. `DATABASE_REQUIRED` (default false) raises from the lifespan when the pool does not open. |
| Compose | `docker-compose.yml` | `DATABASE_URL` and `DATABASE_REQUIRED` can come from the environment. The local Postgres URL and `false` remain the defaults. |
| Docs | `docs/deployment/aws.md`, `docs/decisions/spo-132-aws-rds-s3/decision_20261111_rds-and-s3.md`, `env.example`, `.env.example` | Env vars, cutover order, rollback order, and the RDS + S3 decision. Placeholders only. |
| Ignore | `.gitignore`, `infra/aws/.gitignore` | Local Terraform state and `*.tfvars`. The example tfvars file stays tracked. |

## Why

The startup print included the password, and a failed `init()` only set the pool to `None`. A remote database that rejects the box IP would look like a healthy API with no persistence. Production has to opt in to a hard failure (`DATABASE_REQUIRED=true`) because the test suite and local compose still start without Postgres.

asyncpg 0.30 already applies `sslmode` and `sslrootcert` from the DSN query string. Copying those into a separate setting would risk two different values. `create_pool` receives `settings.database_url` unchanged.

The box has `pg_restore` 17. That client writes `SET transaction_timeout`, which PostgreSQL 16 rejects, so the migration script stops before restore unless `ALLOW_PG_RESTORE_MISMATCH=1`. The daily dump can still use a v17 client, because that path only dumps.

Single-AZ, a public endpoint with an allowlist, SSE-S3, and the AWS-managed RDS key are the cost and operations choices in the plan. The runtime policy has no delete, and Terraform does not create access keys, so a key cannot land in state. `0.0.0.0/0` is rejected in `variable` validation, not only in a comment.

## Tests / Verification

- Backend pytest: `cd backend && /tmp/nba-venv/bin/python -m pytest -q --tb=line` → 1224 passed, 26 skipped, 6 xfailed, 0 failed.
- Frontend: not touched.
- Integration test: SKIPPED. No AWS account, no `RUN_INTEGRATION`. Script tests use fake `pg_dump`, `pg_restore`, `psql`, and `aws` binaries.
- Fabrication scan: PASS. This change does not mock an external odds or stats API and does not add a hand-typed response body.
- Terraform: `terraform fmt -check -recursive` clean. `terraform init -backend=false` installed hashicorp/aws v5.100.0. `terraform validate` succeeded. `terraform console` with `allowed_cidrs=["0.0.0.0/0"]` reports the validation error and does not call AWS. `terraform plan` and `terraform apply` were not run.

## Follow-ups

- [ ] Eason applies `infra/aws` (or the console fallback) and confirms the current PostgreSQL 16 minor with `describe-db-engine-versions`. Default `engine_version` is `16.15`.
- [ ] The backend host's egress address, and whether it is static, is still unknown. It has to be in `allowed_cidrs` before cutover. The box address recorded on 2026-11-10 was `184.193.214.44/32`; confirm it before use.
- [ ] Install PostgreSQL 16 client tools where the restore runs. The daily dump can stay on the v17 client.
- [ ] Download the RDS CA bundle to the path in `sslrootcert`. It is not committed.
- [ ] Create `sportslab_app` with SQL after apply. Terraform does not create that role.
- [ ] Wire `sync_raw_to_s3.sh` and `pg_dump_to_s3.sh` to a schedule after the first successful sync and dump. The scripts are not cron yet.
- [ ] A new AWS account on the Free plan can be suspended when the credit period ends. Upgrade to the Paid plan before this is the only copy of the data.
- [ ] Local `pg-data` stays for two weeks after cutover. Row counts of the live database were not available from this environment.
