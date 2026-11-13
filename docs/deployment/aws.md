# AWS deployment (RDS PostgreSQL 16 + S3)

Sports Lab keeps Redis local. PostgreSQL and the raw Ball Don't Lie files move to AWS. Terraform for the resources is in `infra/aws/`. Eason runs `terraform apply` on his Mac with his own AWS login. This repository does not call AWS, and no provisioner key is created for anyone else.

The backend and Postgres both run on that Mac until the EC2 host below is serving. Postgres is the `no-vig-nba-postgres` container (`postgres:16-alpine` in `docker-compose.yml`). The Mac is not deployed anywhere and its home IP can change. The allowlist is the real box `/32`, written only in the gitignored `terraform.tfvars`, plus the Mac's current public `/32`. The tracked example uses `198.51.100.10/32` for the box line. `scripts/aws_update_my_ip.sh` rewrites only the Mac line.

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

Startup prints the database URL with the password replaced by `***`. A failed `db.init()` is logged the same way. With `DATABASE_REQUIRED=false` the process keeps running. With `DATABASE_REQUIRED=true` startup raises. There is no projection service and no SportsDataIO client.

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

If verify failed after the restore, re-run with `--verify-only`. That skips the dump and the restore and compares row counts, `max(id)`, and sequence `last_value` again. If either side lists zero public tables, it exits 1 and does not print `ok:`. The error line is the two counts. Zero sequences is a match only when both sides list zero.

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

Apply also creates security group `sportslab-app` (output `app_security_group_id`) and attaches the EC2 instance to it. The group resource itself still has no inline ingress, so its description stays as first applied. Separate rules open TCP 80 and 443, plus TCP 22 only when `enable_ssh` is true. RDS already allows TCP 5432 from that group, by security group id, and from any id in `rds_allowed_security_group_ids` (default empty). Once the host is serving, set `allowed_cidrs = []` in the gitignored `terraform.tfvars` and apply again. That removes the Mac and box CIDR rules. Do not run `scripts/aws_update_my_ip.sh --apply` after that, because `--apply` passes those two CIDRs back in. `0.0.0.0/0` and `::/0` stay rejected.

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

The instance is placed in `try(sort(public_subnet_ids)[0], null)`. A bare `[0]` raises `Invalid index` while the list is still empty, and the instance precondition never runs. `try` returns null instead, so plan stops with: `public_subnet_ids is empty. Set vpc_id to a VPC whose subnets have MapPublicIpOnLaunch=true.` The DB subnet group also requires those subnets to cover at least two availability zones. A lifecycle precondition reports that. It does not replace the group.

A `check` block cannot point this case at `vpc_id`. `data.aws_vpc.selected` fails the plan with `no matching EC2 VPC found` before any check runs. Changing that data source so the lookup is optional would change the flow this stack already applies. Set `vpc_id` in `terraform.tfvars` instead.

## Rollback

- Before the backend is pointed at RDS: leave `.env` unset for `DATABASE_URL`. `docker compose` still uses `postgresql://novig:novig@postgres:5432/novig_nba`. Start the compose backend again.
- After cutover: remove `DATABASE_URL` from `.env` (or set it back to that compose URL) and restart the compose backend. The compose Postgres port is not published, so a host process on the Mac should not be pointed at `localhost:5432`. Rows written to RDS after cutover are not in `pg-data` unless you dump RDS and restore locally with the same script and a PostgreSQL 16 client. Keep `pg-data` until RDS has run cleanly for two weeks.

## Scripts

| Script | Required environment | What it refuses to do |
|---|---|---|
| `scripts/db_migrate_to_rds.sh` | `LOCAL_DATABASE_URL`, `RDS_DATABASE_URL` | Print URLs or passwords. Run `pg_restore` when its major version is not 16 (override: `ALLOW_PG_RESTORE_MISMATCH=1`). Restore when the two URLs are identical. Default client is `docker exec no-vig-nba-postgres`. `PG_CLIENT=docker-run` uses `docker run --rm postgres:16`. Adds `sslmode=require` on the RDS URL when `sslmode` is absent. `--verify-only` skips the dump, the restore, and that version gate, and only compares row counts, `max(id)`, and sequence `last_value`. If verify failed after a restore, re-run with `--verify-only`. Zero public tables on either side exits 1. Zero sequences is allowed only when both sides list zero. |
| `scripts/aws_update_my_ip.sh` | none (uses curl) | Call AWS by itself. It rewrites gitignored `terraform.tfvars` and prints `terraform apply`. `--apply` is the only way it launches terraform. |
| `scripts/sync_raw_to_s3.sh` | `S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | `--delete`. Paths default to `/workspace/bdl-cache`, `/workspace/bdl-archive`, `/workspace/bdl-eval/samples` and can be overridden with `BDL_CACHE_DIR`, `BDL_ARCHIVE_DIR`, `BDL_SAMPLES_DIR`. |
| `scripts/pg_dump_to_s3.sh` | Those AWS variables plus `RDS_DATABASE_URL` or `DATABASE_URL` | Print the database URL. `DUMP_DATE=YYYY-MM-DD` overrides the UTC date in the object key. The bucket keeps each current dump for 90 days; this script does not delete. |

If a required variable is missing, the script prints help and a dry-run line and exits 2. It does not call `pg_dump`, `pg_restore`, or `aws`.

## EC2 backend

One Amazon Linux 2023 arm64 instance in us-east-2 runs Caddy, the FastAPI process, and Redis. The scheduler stays inside the API process. There is no Postgres container and no ElastiCache. Images come from GHCR. The repository is public, so the instance pulls anonymously. RDS stays the database. Eason runs `terraform apply` from `infra/aws` on his Mac. This repository does not call AWS.

Terraform adds, on top of the RDS and S3 stack:

- `instance_type` default `t4g.small`. The AMI is the SSM public parameter `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64`.
- A 30 GB encrypted gp3 root (`root_volume_gb`). IMDSv2 is required. Hop limit is 2 so the container can use the instance role.
- An Elastic IP (`terraform output eip`) and the instance id (`terraform output instance_id`). The instance subnet is `try(sort(local.public_subnet_ids)[0], null)`, the first public subnet in the VPC from `vpc_id` (or the default VPC when that variable is unset). See [If your account has no default VPC](#if-your-account-has-no-default-vpc).
- The existing `sportslab-app` security group. TCP 80 and 443 are open to the internet. TCP 22 is closed unless `enable_ssh = true`, and then only from `allowed_cidrs`. 8000 and 6379 are not published. Egress stays an inline block on `aws_security_group.app`, so Terraform keeps that one outbound rule. Ingress is not declared inline. Those ports are separate `aws_security_group_rule` resources, and the provider leaves them alone. Do not add an inline `ingress` block to that security group. It would make the group authoritative for ingress and delete the separate rules.
- An instance role (`terraform output instance_role_arn`). Managed policies are `AmazonSSMManagedInstanceCore` and `CloudWatchAgentServerPolicy`. S3 is the same prefix policy as the runtime user (list, get, put; no delete). SSM `GetParameter`, `GetParameters`, and `GetParametersByPath` are limited to `/sportslab/prod` and `/sportslab/prod/*`. `kms:Decrypt` is only via `ssm.<region>.amazonaws.com` and only when the encryption context parameter ARN is under `/sportslab/prod/`. No access keys are created.
- A system-status alarm that recovers the instance, a CloudWatch agent config for disk and memory, and a disk alarm at 80%. `alarm_email` empty skips the SNS topic. A non-empty value creates an email subscription that stays pending until the inbox confirms it.
- `domain` default empty. Empty derives `<eip-with-dashes>.sslip.io` from the Elastic IP. A non-empty hostname wins. User data writes `DOMAIN` and the optional `ACME_EMAIL` to `/etc/sportslab/caddy.env` on first boot only. Changing either later does not replace the instance. Edit that file and recreate the Caddy container.
- `enable_github_deploy_role` default false. When true, `github_repository` must be `owner/name`. The role can `ssm:SendCommand` only to this instance. Output `github_deploy_role_arn`.

`terraform plan` and `terraform apply` are Eason's commands. They are not part of CI.

### Secrets in SSM

Use Parameter Store SecureString under `/sportslab/prod/<NAME>`, with the default `aws/ssm` key. Standard parameters are the chosen store. Do not put the values in git, Terraform, or chat.

Create the parameters in the console or with the CLI. The example below is the shape. Replace the value locally and do not echo it back:

```bash
openssl rand -hex 32 | aws ssm put-parameter \
  --region us-east-2 \
  --name /sportslab/prod/VERCEL_PROXY_SECRET \
  --type SecureString \
  --value file:///dev/stdin
```

`openssl rand -hex 32` runs on the Mac. The same secret goes in the Vercel project environment as `VERCEL_PROXY_SECRET`. Frontend's rewrite sends it as the header `x-sportslab-proxy-secret`. The header name is `PROXY_SECRET_HEADER` in `backend/app/middleware/rate_limit.py`.

`PROXY_SECRET_REQUIRED` defaults to false. `deploy/docker-compose.prod.yml` pins it to `false`, and that compose value wins over `/etc/sportslab/backend.env`, so an SSM parameter cannot turn the check on by itself. When the flag is true and `VERCEL_PROXY_SECRET` is set, every request except the health routes requires a matching `x-sportslab-proxy-secret`. A missing, blank, or wrong header is HTTP 403. That includes `OPTIONS` and any SSE route, because the check runs before the route. The process refuses to start when the flag is true and the secret is empty. `GET /api/health` and `GET /health` stay open. The compose healthcheck and `deploy/remote-up.sh` call `http://127.0.0.1:8000/api/health` inside the backend container, so they do not hit Caddy. A public request to `http://<hostname>/health` is redirected to HTTPS. There is no separate readiness route.

The flag stays off in compose until the Vercel deployment is the frontend from #63 (`88f1c66`). That code is in this repo now: `frontend/lib/api.ts` calls the same-origin `/api/backend` prefix, and `frontend/middleware.ts` forwards it to `BACKEND_API_URL` with the secret. There is no `EventSource`. After that build is what Vercel serves, change the compose line to `"true"` and redeploy the backend. A browser preflight stays on the Next.js origin. This backend still answers a direct `OPTIONS` with 403 when the flag is on.

The paths `fetchApi` calls, all under `/api/backend` in the browser:

- `GET /api/nba/events`, `POST /api/nba/props/no-vig`, `GET /api/nba/players/suggest`, `GET /api/health`
- `GET /api/nba/csv/players`, `GET /api/nba/player-history`, `GET /api/nba/player-dd-history`
- `GET /api/wnba/csv/players`, `GET /api/wnba/player-history`, `GET /api/wnba/player-dd-history`
- `GET /api/wnba/events`, `POST /api/wnba/props/no-vig`, `GET /api/wnba/players/suggest`
- `GET /api/nba/daily-picks`, `POST /api/nba/daily-picks/trigger`
- `GET /api/wnba/daily-picks`, `POST /api/wnba/daily-picks/trigger`
- `POST /api/nba/agent/chat`
- `GET /api/nba/lineups`, `GET /api/nba/lineups/{team}`, `GET /api/wnba/lineups/{team}`, `GET /api/nba/lineups/refresh`
- `GET /api/nba/events/{id}/reads`, `GET /api/nba/events/{id}/props`

Do not create `SPORTSDATA_API_KEY` or any projection parameter. Nothing in the app reads them. `Settings` uses `extra=ignore`, so a leftover name does not stop startup, and it also does nothing.

`pull-ssm-env.sh` copies every parameter under `/sportslab/prod/` into `/etc/sportslab/backend.env`. `GHCR_PULL_USER` and `GHCR_PULL_TOKEN` go to `/etc/sportslab/ghcr.env` instead. Names Eason creates:

| Name | Type | Required | Purpose |
|---|---|---|---|
| `DATABASE_URL` | SecureString | required | RDS DSN. `sslmode=verify-full` and `sslrootcert=/app/certs/global-bundle.pem`. Compose sets `DATABASE_REQUIRED=true`, so a bad URL stops startup. |
| `BALLDONTLIE_API_KEY` | SecureString | required for NBA injuries | `nba_injuries_refresh` reads it. Empty skips the call. The process still starts. |
| `ODDS_API_KEY` | SecureString | optional for startup | The Odds API. WNBA odds read it. NBA events, props, snapshots, and daily analysis use the same provider, so those calls fail at the provider when it is empty. Health, CSV players, and the scheduler still start. |
| `OPENAI_API_KEY` | SecureString | optional for startup | Agent chat. `ChatOpenAI` reads it from the environment. Other routes do not. |
| `VERCEL_PROXY_SECRET` | SecureString | required before the flag is on | Shared with the Vercel rewrite. Compose pins `PROXY_SECRET_REQUIRED=false`, so an empty secret still starts. |
| `CORS_ALLOWED_ORIGINS` | String | optional | Browser origins. Empty falls back to `ALLOWED_ORIGINS`. |
| `CORS_ALLOWED_ORIGIN_REGEX` | String | optional | Preview hostnames. Empty means no regex. |
| `BOT_API_KEYS` | SecureString | optional | Discord bot free tier. |
| `BOT_API_KEYS_PREMIUM` | SecureString | optional | Discord bot premium tier. |
| `GHCR_PULL_USER` | SecureString | optional | Only when the GHCR package is private. |
| `GHCR_PULL_TOKEN` | SecureString | optional | Only when the GHCR package is private. |

Do not store `PROXY_SECRET_REQUIRED` in SSM. The compose file pins it and wins. User data downloads the public RDS CA to `/opt/sportslab/certs/global-bundle.pem` and compose mounts it at `/app/certs/global-bundle.pem`.

`deploy/pull-ssm-env.sh` writes `/etc/sportslab/backend.env` mode 600. It does not print values. `GHCR_PULL_USER` and `GHCR_PULL_TOKEN`, if present, go to `/etc/sportslab/ghcr.env` instead, also mode 600, and are used only when the GHCR package is private.

To rotate `VERCEL_PROXY_SECRET`: set the new secret on Vercel and in SSM, then redeploy both. On the host that is `deploy/pull-ssm-env.sh` and `docker compose up -d`. Once `PROXY_SECRET_REQUIRED` is true, non-health requests return 403 while the two sides differ. While the flag stays false, a mismatch only changes the rate-limit key. Do not put the new value in git or chat. Leading and trailing spaces on the loaded secret are stripped.

### First deploy

1. Apply the Terraform stack. Read `backend_api_url`, `eip`, `instance_id`, and `instance_role_arn`.
2. Store the SecureStrings, including `DATABASE_URL` and `VERCEL_PROXY_SECRET`.
3. Connect with Session Manager (no SSH key):

```bash
aws ssm start-session --target "$(terraform output -raw instance_id)" --region us-east-2
```

4. On the instance, checkout the commit that contains `deploy/` and start the stack. `latest` is the moving tag. A git SHA is better:

```bash
sudo mkdir -p /opt/sportslab
sudo git clone https://github.com/eason034056/nba-player-stats-analysis.git /opt/sportslab/repo
cd /opt/sportslab/repo
sudo git fetch --depth 1 origin <git-sha>
sudo git checkout --detach --force FETCH_HEAD
sudo deploy/remote-up.sh <git-sha>
```

`remote-up.sh` pulls `/sportslab/prod/*`, pulls the GHCR image, and starts compose. It prints `healthy` after the backend container answers `http://127.0.0.1:8000/api/health`. It does not print secrets and it does not call port 80.

5. Read the origin and point Vercel at it. Do this for Production and Preview:

```bash
terraform output -raw backend_api_url
```

Set `BACKEND_API_URL` to that value. It looks like `https://203-0-113-10.sslip.io` when `domain` is empty, with dots in the Elastic IP replaced by hyphens. No path. Set `VERCEL_PROXY_SECRET` to the same value stored in SSM, then redeploy the frontend. Check the certificate from the Mac:

```bash
curl -I https://203-0-113-10.sslip.io/health
```

Use the hostname from the output, not this example. A 200 means Caddy has a certificate and the backend answered. A redirect from `http://` to `https://` on that path is expected. The deploy workflow uses `remote-up.sh`, which checks the container address instead of this public URL, because port 80 redirects before the certificate is required for the script to pass.

`aws_eip.app` is created with `domain = "vpc"` and does not set `instance`. `public_ip` is known as soon as the address exists. The instance user data reads `local.backend_hostname`, which uses that address when `var.domain` is empty. `aws_eip_association.app` attaches the address after the instance exists. The address resource does not depend on the instance, so user data and the Elastic IP are not a cycle.

### sslip.io and certificates

`deploy/Caddyfile.https` is the production config. The hostname block reverse-proxies to `backend:8000` with `flush_interval -1` and 125 second timeouts. The only `http://` site redirects to HTTPS, and it skips `/.well-known/acme-challenge/` so HTTP-01 is not redirected. Port 80 is open for that challenge and for the redirect. Port 443 is open for HTTPS. No other inbound port is open unless `enable_ssh` is true.

Caddy stores the certificate in the `caddy_data` volume. `docker compose up` does not remove that volume, so a redeploy renews instead of asking for a new certificate. Do not run `docker compose down -v`.

`acme_email` is optional. Empty leaves the Caddy `email` option out. Let's Encrypt issues either way. A non-empty value is written to `/etc/sportslab/caddy.env` as `ACME_EMAIL` and the entrypoint inserts it.

Let's Encrypt's rate-limit page, updated 2026-08-05, says a registered domain is the registrar name identified with the Public Suffix List, and that up to 50 new certificates per registered domain are issued every 7 days. That limit is global across accounts. The same page says up to 5 certificates are issued for one exact set of identifiers every 7 days. The public suffix list fetched from `https://publicsuffix.org/list/public_suffix_list.dat` on 2026-11-11 does not contain `sslip.io`. Under those two sources, `203-0-113-10.sslip.io` counts against the registered domain `sslip.io`, shared with every other `sslip.io` hostname. There is no Let's Encrypt page in this check that names `sslip.io` itself. If the public suffix list later adds `sslip.io`, each hostname would be its own registered domain. That later change is not something this page can confirm.

If issuance fails, Caddy's automatic HTTPS docs say it retries once, tries the next challenge type, then tries the next issuer. The default issuers are Let's Encrypt and then ZeroSSL. If both fail, it backs off, at most one day between attempts, for up to 30 days. During Let's Encrypt retries it also tries the staging environment. Leave `caddy_data` in place and read `docker logs sportslab-caddy`. Deleting the volume spends another certificate from the exact-set limit. Do not change Vercel until `curl -I https://<hostname>/health` succeeds.

### Switching to a real domain

1. Create a DNS A record for the hostname pointing at `terraform output -raw eip`.
2. Set `domain` in `terraform.tfvars` to that bare hostname (no `https://`). Apply, or skip the apply and edit the host file in the next step. User data does not rewrite `/etc/sportslab/caddy.env` on a reboot.
3. On the instance, set `DOMAIN=` in `/etc/sportslab/caddy.env` to the same hostname.
4. `docker compose -f deploy/docker-compose.prod.yml up -d` so Caddy loads the new name. The old certificate stays in `caddy_data` until it expires. The new name gets its own certificate.
5. Change Vercel `BACKEND_API_URL` on Production and Preview to `https://<domain>` with no path, and redeploy the frontend.

### Cutover order

1. Apply `infra/aws` once. That apply creates RDS, S3, and this EC2 host together. #62 and #65 are already on `dev`.
2. Run the RDS migration in the section above. The Mac and the box can still open 5432.
3. Deploy the EC2 host and point Vercel `BACKEND_API_URL` at `terraform output -raw backend_api_url`. Confirm `curl -I https://<hostname>/health` and a real read against RDS.
4. As a separate later apply, make RDS private: `allowed_cidrs = []` and `publicly_accessible = false`. RDS still allows the app security group, so the instance keeps its connection. Do not do this before the host is the only client that must reach the database.

After step 4, a Mac or the box reaches Postgres through the instance:

```bash
aws ssm start-session \
  --target i-INSTANCE \
  --region us-east-2 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["RDS_HOSTNAME"],"portNumber":["5432"],"localPortNumber":["5432"]}'
```

Then connect to `127.0.0.1:5432`. The security group does not need the Mac's IP.

### Rate limits behind the rewrite

Vercel calls this API from its own egress addresses. slowapi no longer keys only on that address. If `VERCEL_PROXY_SECRET` is non-empty and `x-sportslab-proxy-secret` matches it, the key is `x-real-ip`, or else the left-most `x-forwarded-for` entry, after `ipaddress` accepts it. Any other case uses `request.client.host`.

On this host that host is not the Caddy container. uvicorn `--proxy-headers` rewrites `request.client` from `X-Forwarded-For` before the key function runs, and only when the TCP peer is exactly `172.30.133.10`. `--forwarded-allow-ips` is that address, not `*` and not the subnet. Caddy does not set `trusted_proxies`, so it replaces `X-Forwarded-For` with the single TCP peer it accepted: a Vercel egress address, or a client that connected to port 80 or 443. A client cannot spoof that value by sending their own `X-Forwarded-For`. The subnet `172.30.133.0/24` is pinned so `172.30.133.10` stays on Caddy. The backend port is not published. If `trusted_proxies` is added later, Caddy would keep the client-supplied chain, and this path has to be reviewed again.

With `PROXY_SECRET_REQUIRED=true`, a request that fails the secret check is 403 before the route runs, including `OPTIONS` and a streaming response. The slowapi middleware is outside that check, so the 403 still counts toward the limit. `/api/health` and `/health` do not require the header. `x-real-ip` is the key when the secret matches, ahead of `X-Forwarded-For`, because Caddy replaces `X-Forwarded-For` with the egress address while the frontend sets `x-real-ip` to the browser address.

Browser CORS is not required for the Vercel rewrite, because that call is server to server. The allow-list stays for any browser client. `CORS_ALLOWED_ORIGINS` is the list. `ALLOWED_ORIGINS` is the alias. `CORS_ALLOWED_ORIGIN_REGEX` is optional and is passed to `allow_origin_regex`. `*` is rejected. Nothing in this API authenticates from the Origin header.

Example production origin, once SPO-134 has the real project name: `https://<project>.vercel.app`.

Example preview regex, covering `https://<project>-git-<branch>-<scope>.vercel.app` and `https://<project>-<hash>-<scope>.vercel.app`:

```text
^https://sports-lab(-git-[a-z0-9-]+-team|-[a-z0-9]+-team)\.vercel\.app$
```

Replace `sports-lab` and `team` when the real names exist. Leave the regex empty until then.

### Agent chat and the 120 second rewrite

`POST /api/nba/agent/chat` and `POST /api/wnba/agent/chat` run the LangGraph in process. One pass is a planner model call, tool calls, a critic call, and a synthesizer call. The graph can repeat that up to three times. A slip review or a board review does up to six of those one after another. The model client has no short deadline of its own. A single chat can therefore run well past 120 seconds, which is when Vercel drops an external rewrite.

The routes stop the work at `agent_chat_timeout_seconds` (default 100, maximum 105) and return HTTP 504 with a message that names the limit and tells the client to try one pick. Caddy's proxy read timeout and response-header timeout are 125 seconds, so the 504 is not cut off by Caddy. There is no SSE route today. If one is added, responses already get `Cache-Control: no-cache, no-transform`, and Caddy uses `flush_interval -1`.

### Scheduler on a larger instance

Leave the scheduler in the API process on `t4g.small`. Splitting it is a later change: a second container that only runs the scheduler, the API lifespan skipping that start, and `instance_type = "t4g.medium"` (2 vCPU, 4 GiB). Do not `docker build` on this host.

### GitHub deploy workflow

`.github/workflows/deploy-backend.yml` is `workflow_dispatch` only. The job exits before any build unless the repository variable `DEPLOY_ENABLED` is `true`. The default branch is `master`. There is no `main`. To also run on push, add `push: branches: [master]` next to `workflow_dispatch` and keep the `DEPLOY_ENABLED` check. Do not filter on `main`.

The workflow builds `linux/arm64` with buildx, pushes `ghcr.io/<owner>/<repo>/backend:<sha>` and `:latest`, then `aws ssm send-command` runs `deploy/remote-up.sh`. It assumes `AWS_DEPLOY_ROLE_ARN` with GitHub OIDC. Also set repository variables `AWS_REGION=us-east-2` and `EC2_INSTANCE_ID`. No static AWS keys are required. After the first push, set the GHCR package to public so the instance can pull without a token. If it stays private, store `GHCR_PULL_USER` and `GHCR_PULL_TOKEN` in SSM.

GHCR is the registry because the repository is public and an anonymous pull needs no IAM pull policy and no registry storage charge. A private package needs the SSM token above. ECR would avoid the anonymous rate limit and cost about $0.10 per GB-month, and the instance role would need pull permissions. That is not this stack.

### Cost estimate

These are on-demand estimates for us-east-2, 730 hours, before tax. They are not a bill. Sources, no signed AWS calls:

- EC2 Linux t4g and gp3: the Amazon EC2 current us-east-2 price list and the Ohio Linux on-demand calculator map, publication 2026-11-10 11:38 AM America/Chicago (`2026-11-10T17:38:52Z`). Context: https://aws.amazon.com/ec2/pricing/on-demand/ and https://aws.amazon.com/ebs/pricing/
- Public IPv4: Amazon VPC us-east-2 price list, 2026-11-05 12:19 PM America/Chicago.
- CloudWatch: Amazon CloudWatch us-east-2 price list, 2026-11-04 3:35 PM America/Chicago. https://aws.amazon.com/cloudwatch/pricing/
- Data transfer: AWS Data Transfer us-east-2 price list, 2026-11-10 5:29 PM America/Chicago.
- SSM Session Manager for a standard instance is free.

| Line | Estimate |
|---|---|
| t4g.small Linux, $0.0168/hour, 730 h | $12.26 |
| t4g.micro, for comparison | $6.13 |
| t4g.medium, for comparison | $24.53 |
| gp3 root 30 GB at $0.08/GB-month (baseline IOPS included) | $2.40 |
| Public IPv4 in use, $0.005/hour | $3.65 |
| CloudWatch alarms and the disk/memory metrics | about $0, inside the free bundle of 10 alarms and 10 metrics |
| Data transfer out | $0 while monthly traffic stays inside the first 100 GB |
| **This host (t4g.small + 30 GB + Elastic IP)** | **about $18.3–19** |

Together with the SPO-132 estimate of about $18–21 (that estimate includes the RDS public IPv4), the two stacks are about $36–40 per month. After RDS is private and its public IPv4 is gone, subtract about $3.65, so about $32–36 per month. Do not assume Free Tier credits. CPU credits, transfer past 100 GB, or extra metrics add a few dollars. This is an estimate from those public price lists, not an invoice.
