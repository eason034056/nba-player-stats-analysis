# AWS deployment (RDS PostgreSQL 16 + S3)

Sports Lab keeps Redis local. PostgreSQL and the raw Ball Don't Lie files move to AWS. Terraform for the resources is in `infra/aws/`. Eason runs `terraform apply` on his Mac with his own AWS login. This repository does not call AWS, and no provisioner key is created for anyone else.

The backend and Postgres both run on that Mac. Postgres is the `no-vig-nba-postgres` container (`postgres:16-alpine` in `docker-compose.yml`). The Mac is not deployed anywhere and its home IP can change. The allowlist is the real box `/32`, written only in the gitignored `terraform.tfvars`, plus the Mac's current public `/32`. The tracked example uses `198.51.100.10/32` for the box line. `scripts/aws_update_my_ip.sh` rewrites only the Mac line.

Step-by-step for that Mac, in Traditional Chinese: [docs/deployment/aws-steps-zh-TW.md](aws-steps-zh-TW.md).

Placeholders only in `env.example` (`cp env.example .env`). Never commit `.env`, `terraform.tfvars`, or `terraform.tfstate`.

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

If the password contains `@`, `:`, `/`, or `%`, percent-encode it before it goes into the URL (`/` becomes `%2F`). An unencoded `/` is not a legal password character in a URL. Startup still masks a password that was pasted with a raw `/`, and it masks a `password=` query value without dropping the rest of the query.

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

The AWS account already exists. Check its plan and billing, set a monthly $25 budget alarm, then apply. Do not treat this as creating a new account or as an upgrade. There is no Paid-plan button. $25 is a budget cap, not an estimate. The `db.t4g.micro` compute price is about $0.016 per hour (about $12 per month) in both `us-east-1` and `us-east-2`. On top of that, expect gp3 storage, backup storage beyond the free allocation, data transfer, and T4g unlimited CPU credits.

1. On the Mac, `aws configure` with Eason's own keys. Those keys stay in `~/.aws`. They do not go in the repo or in chat.
2. `cd infra/aws && cp terraform.tfvars.example terraform.tfvars`. Set the bucket name. Replace the example box line `198.51.100.10/32` with the real box `/32` in that gitignored file, and set the `# mac-home` line to the Mac's current public `/32`. `./scripts/aws_update_my_ip.sh` rewrites the Mac line and prints `terraform apply`; it does not call AWS unless `--apply` is passed.
3. `terraform init`, `terraform plan`, `terraform apply`. If plan reports `no matching EC2 VPC found`, the account has no default VPC. Follow [If your account has no default VPC](#if-your-account-has-no-default-vpc), then plan again. Read `db_endpoint`, `master_user_secret_arn`, `bucket_name`, `app_security_group_id`, `vpc_id`, and `public_subnet_ids`. The migration and dump scripts do not call Secrets Manager. They read `RDS_DATABASE_URL`, which you build. `SecretString` is JSON. Take only the password field:

```bash
aws secretsmanager get-secret-value \
  --secret-id "$(terraform output -raw master_user_secret_arn)" \
  --query SecretString --output text \
  --region us-east-2 | jq -r .password
```

Do not paste that JSON, or the password, into the URL, into chat, or into git. The terminal keeps the output. Percent-encode `@`, `:`, `/`, and `%` in the password before it goes into `RDS_DATABASE_URL`.
4. Create `sportslab_app`. Start the backend once against the empty database and confirm the six tables and the SPO-117 key (`\d odds_line_snapshots`). Stop it before the restore. If that startup created tables, drop them or recreate `novig_nba` so the restore target is empty.
5. Stop the local backend so the scheduler is not writing. Dump with the Postgres 16 container (the compose port is not published to the Mac):

Do not type the DSN on the command line. Shell history would keep the password. Put the two URLs in a mode `600` file outside the repo, or type the RDS URL with `read -s` so it is not echoed and not saved as a command.

```bash
touch ~/.sportslab-migrate.env
chmod 600 ~/.sportslab-migrate.env
# LOCAL_DATABASE_URL=postgresql://novig:novig@localhost:5432/novig_nba
# RDS_DATABASE_URL=postgresql://sportslab_admin:ENCODED@ENDPOINT:5432/novig_nba
set -a
source ~/.sportslab-migrate.env
set +a
./scripts/db_migrate_to_rds.sh
```

```bash
read -s -p "Local URL: " LOCAL_DATABASE_URL
echo
read -s -p "RDS URL: " RDS_DATABASE_URL
echo
export LOCAL_DATABASE_URL RDS_DATABASE_URL
./scripts/db_migrate_to_rds.sh
```

The default is `docker exec no-vig-nba-postgres`. In that container, `localhost:5432` is the database; the same URL does not work from a process on the Mac, because compose does not publish 5432. `PG_CLIENT=docker-run` uses a throwaway `postgres:16` client instead. If the RDS URL has no `sslmode`, the script adds `sslmode=require` for the restore and the RDS checks. It does not print either URL. A non-16 `pg_restore` is refused.

6. Put the `sportslab_app` URL in the Mac's `.env` as `DATABASE_URL`, with `sslmode=verify-full` and the RDS CA path. Set `DATABASE_REQUIRED=true` after the first clean start. Logs show the masked host, then "tables are ready".
7. Run `scripts/sync_raw_to_s3.sh` once. Schedule `scripts/pg_dump_to_s3.sh` daily at 10:00 UTC. Each object is `pg-dumps/<UTC date>.dump`. The bucket lifecycle keeps current dumps for 90 days. Keep the local `pg-data` volume for two weeks.

When the home IP changes, run `scripts/aws_update_my_ip.sh` and then the printed `terraform apply`. Until that apply finishes, the Mac cannot open 5432.

Apply also creates security group `sportslab-app` (output `app_security_group_id`). It has no ingress rules. It exists so a later EC2 instance (SPO-133) can attach to it. RDS already allows TCP 5432 from that group, by security group id, and from any id in `rds_allowed_security_group_ids` (default empty). Once that EC2 backend is live and attached to `sportslab-app`, set `allowed_cidrs = []` in the gitignored `terraform.tfvars` and apply again. That removes the Mac and box CIDR rules. Do not run `scripts/aws_update_my_ip.sh --apply` after that, because `--apply` passes those two CIDRs back in. `0.0.0.0/0` and `::/0` stay rejected.

## If your account has no default VPC

`terraform plan` looks up the region's default VPC when `vpc_id` is unset. An account with no default VPC stops there:

```text
Error: no matching EC2 VPC found
```

List the VPCs. Do not commit the ids this prints.

```bash
aws ec2 describe-vpcs --query 'Vpcs[].{id:VpcId,cidr:CidrBlock,default:IsDefault,name:Tags[?Key==`Name`]|[0].Value}' --output table
```

Pick the VPC whose main route table sends `0.0.0.0/0` to an `igw-` gateway, and whose subnets have `MapPublicIpOnLaunch` true. `vpc-0123456789abcdef0` below is a placeholder. Replace it with the id from the table.

```bash
aws ec2 describe-route-tables \
  --filters Name=vpc-id,Values=vpc-0123456789abcdef0 \
  --query 'RouteTables[?Associations[?Main]].{id:RouteTableId,defaultRoute:Routes[?DestinationCidrBlock==`0.0.0.0/0`].GatewayId}' \
  --output table
```

```bash
aws ec2 describe-subnets \
  --filters Name=vpc-id,Values=vpc-0123456789abcdef0 \
  --query 'Subnets[].{id:SubnetId,az:AvailabilityZone,public:MapPublicIpOnLaunch,cidr:CidrBlock}' \
  --output table
```

Add the id to the gitignored `terraform.tfvars`:

```hcl
vpc_id = "vpc-0123456789abcdef0"
```

Run `terraform plan` again. Leave the variable unset to keep the default VPC. An empty string is rejected. It does not mean "use the default".

## Rollback

- Before the backend is pointed at RDS: leave `.env` unset for `DATABASE_URL`. `docker compose` still uses `postgresql://novig:novig@postgres:5432/novig_nba`. Start the compose backend again.
- After cutover: remove `DATABASE_URL` from `.env` (or set it back to that compose URL) and restart the compose backend. The compose Postgres port is not published, so a host process on the Mac should not be pointed at `localhost:5432`. Rows written to RDS after cutover are not in `pg-data` unless you dump RDS and restore locally with the same script and a PostgreSQL 16 client. Keep `pg-data` until RDS has run cleanly for two weeks.

## Scripts

| Script | Required environment | What it refuses to do |
|---|---|---|
| `scripts/db_migrate_to_rds.sh` | `LOCAL_DATABASE_URL`, `RDS_DATABASE_URL` | Print URLs or passwords. Run `pg_restore` when its major version is not 16 (override: `ALLOW_PG_RESTORE_MISMATCH=1`). Restore when the two URLs are identical. Default client is `docker exec no-vig-nba-postgres`. `PG_CLIENT=docker-run` uses `docker run --rm postgres:16`. Adds `sslmode=require` on the RDS URL when `sslmode` is absent. |
| `scripts/aws_update_my_ip.sh` | none (uses curl) | Call AWS by itself. It rewrites gitignored `terraform.tfvars` and prints `terraform apply`. `--apply` is the only way it launches terraform. |
| `scripts/sync_raw_to_s3.sh` | `S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | `--delete`. Paths default to `/workspace/bdl-cache`, `/workspace/bdl-archive`, `/workspace/bdl-eval/samples` and can be overridden with `BDL_CACHE_DIR`, `BDL_ARCHIVE_DIR`, `BDL_SAMPLES_DIR`. |
| `scripts/pg_dump_to_s3.sh` | Those AWS variables plus `RDS_DATABASE_URL` or `DATABASE_URL` | Print the database URL. `DUMP_DATE=YYYY-MM-DD` overrides the UTC date in the object key. The bucket keeps each current dump for 90 days; this script does not delete. |

If a required variable is missing, the script prints help and a dry-run line and exits 2. It does not call `pg_dump`, `pg_restore`, or `aws`.
