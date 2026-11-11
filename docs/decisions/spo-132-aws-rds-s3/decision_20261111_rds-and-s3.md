# Decision — RDS PostgreSQL 16 and S3 for Sports Lab data

- **Ticket:** SPO-132
- **Date:** 2026-11-11
- **Status:** Accepted

## Context

The system of record is the Postgres started by `docker-compose.yml` (`postgres:16-alpine`, database `novig_nba`). Six tables are created by `SCHEMA_SQL` on startup. Redis is a cache and stays local. Raw Ball Don't Lie files live on the box under `/workspace/bdl-cache`, `/workspace/bdl-archive`, and `/workspace/bdl-eval/samples`. There is no hosting config in the repo, so the backend's egress address is not known yet.

`asyncpg==0.30.0` already parses `sslmode` and `sslrootcert` from the DSN. Startup used to print that DSN, password included, and a failed `db.init()` left the pool as `None` while the API kept serving.

## Decision

Provision one Single-AZ RDS PostgreSQL 16 instance (`db.t4g.micro`, gp3 20 GB, autoscaling to 50 GB, backups kept 7 days) and one private S3 bucket, described in `infra/aws/` and applied by Eason. No Multi-AZ. The instance is publicly reachable and the security group allows TCP 5432 only from `allowed_cidrs`. `0.0.0.0/0` is rejected by variable validation.

Encryption at rest uses the AWS-managed key `aws/rds`. The master password is RDS-managed in Secrets Manager (`manage_master_user_password = true`). Terraform does not create access keys and does not output the password. The runtime IAM user can `s3:GetObject`, `s3:PutObject`, and `s3:ListBucket` on `bdl-raw/`, `bdl-archive/`, `bdl-samples/`, and `pg-dumps/` only. It cannot delete objects.

S3 current objects larger than 128 KB move to Standard-IA after 30 days and to Glacier Instant Retrieval after 90. Noncurrent versions expire after 30 days. `pg-dumps/` current objects expire after 90 days. TLS is required by the bucket policy.

The app keeps SSL configuration in the DSN. `DATABASE_REQUIRED` defaults to false so local tests and dev without Postgres still boot, and production sets it true. Logs print the DSN with the password replaced by `***`.

Logical dump (`scripts/pg_dump_to_s3.sh`) and the S3 sync run in addition to RDS automated backups. The local `pg-data` volume stays for two weeks after cutover.

## Why this and not the alternatives

- **Multi-AZ** doubles instance and storage cost and buys failover the props advisor does not need. Backups still cover durability. An AZ outage means downtime until RDS recovers or a snapshot is restored.
- **A private instance plus a bastion** avoids a public DNS name, but a hosted backend cannot hold an SSM tunnel, and the bastion (or three interface endpoints) costs more than the public IPv4. Revisit a private instance if the backend moves into this VPC.
- **A password in Terraform** would land in state and in the plan. RDS-managed Secrets Manager keeps the value out of both. The app role `sportslab_app` is created with SQL after apply, not in the module.
- **Appending `sslmode` in code** is unnecessary on asyncpg 0.30 and would risk a second, conflicting value. The DSN is passed to `asyncpg.create_pool` unchanged.
- **`DATABASE_REQUIRED` default true** would fail the current test suite and local compose whenever Postgres is down. Production opts in.

## Consequences

- Eason has to apply the module and put the box and the backend egress addresses in `allowed_cidrs`. A home IP that changes will lock the box out until the security group is updated.
- `pg_restore` for the one-time move must be PostgreSQL 16. The box's v17 client emits `SET transaction_timeout`, which PG16 rejects. The daily dump may use the v17 client; that path only dumps.
- Restore expects an empty database. The migration script does not drop existing objects.
- State stays on Eason's machine until someone adds an S3 backend on purpose. `*.tfvars` and `*.tfstate` are gitignored.
