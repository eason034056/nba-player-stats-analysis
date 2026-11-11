# AWS deployment (RDS PostgreSQL 16 + S3)

Sports Lab keeps Redis local. PostgreSQL and the raw Ball Don't Lie files move to AWS. Terraform for the resources is in `infra/aws/`. Eason runs `terraform apply` on his Mac with his own AWS login. This repository does not call AWS, and no provisioner key is created for anyone else.

Until the EC2 cutover below, the backend and Postgres both run on that Mac. Postgres is the `no-vig-nba-postgres` container (`postgres:16-alpine` in `docker-compose.yml`). The Mac is not deployed anywhere and its home IP can change. The fixed allowlist entry is the box, `184.193.214.44/32`. The other entry is the Mac's current public `/32`, updated with `scripts/aws_update_my_ip.sh`. The EC2 section is the host that replaces the Mac process. Do not point production traffic at it until the RDS migration in this document has finished.

Step-by-step for that Mac, in Traditional Chinese: [docs/deployment/aws-steps-zh-TW.md](aws-steps-zh-TW.md).

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

The AWS account already exists. Check its plan and billing, set a monthly $25 budget alarm, then apply. Do not treat this as creating a new account or as an upgrade to the Paid plan.

1. On the Mac, `aws configure` with Eason's own keys. Those keys stay in `~/.aws`. They do not go in the repo or in chat.
2. `cd infra/aws && cp terraform.tfvars.example terraform.tfvars`. Set the bucket name. `allowed_cidrs` is `184.193.214.44/32` plus the Mac's current public `/32`. `./scripts/aws_update_my_ip.sh` rewrites the Mac line and prints `terraform apply`; it does not call AWS unless `--apply` is passed.
3. `terraform init`, `terraform plan`, `terraform apply`. Read `db_endpoint`, `master_user_secret_arn`, and `bucket_name`. Read the master password in Secrets Manager. Do not paste it into chat.
4. Create `sportslab_app`. Start the backend once against the empty database and confirm the six tables and the SPO-117 key (`\d odds_line_snapshots`). Stop it before the restore. If that startup created tables, drop them or recreate `novig_nba` so the restore target is empty.
5. Stop the local backend so the scheduler is not writing. Dump with the Postgres 16 container (the compose port is not published to the Mac):

```bash
LOCAL_DATABASE_URL='postgresql://novig:novig@localhost:5432/novig_nba' \
RDS_DATABASE_URL='postgresql://sportslab_admin:REPLACE_ME@ENDPOINT:5432/novig_nba' \
./scripts/db_migrate_to_rds.sh
```

The default is `docker exec no-vig-nba-postgres`. In that container, `localhost:5432` is the database; the same URL does not work from a process on the Mac, because compose does not publish 5432. `PG_CLIENT=docker-run` uses a throwaway `postgres:16` client instead. If the RDS URL has no `sslmode`, the script adds `sslmode=require` for the restore and the RDS checks. It does not print either URL. A non-16 `pg_restore` is refused.

6. Put the `sportslab_app` URL in the Mac's `.env` as `DATABASE_URL`, with `sslmode=verify-full` and the RDS CA path. Set `DATABASE_REQUIRED=true` after the first clean start. Logs show the masked host, then "tables are ready".
7. Run `scripts/sync_raw_to_s3.sh` once. Schedule `scripts/pg_dump_to_s3.sh` daily at 10:00 UTC. Each object is `pg-dumps/<UTC date>.dump`. The bucket lifecycle keeps current dumps for 90 days. Keep the local `pg-data` volume for two weeks.

When the home IP changes, run `scripts/aws_update_my_ip.sh` and then the printed `terraform apply`. Until that apply finishes, the Mac cannot open 5432.

Apply also creates security group `sportslab-app` (output `app_security_group_id`) and attaches the EC2 instance to it. Ingress on that group is TCP 80 and 443, plus TCP 22 only when `enable_ssh` is true. RDS already allows TCP 5432 from that group, by security group id, and from any id in `rds_allowed_security_group_ids` (default empty). The private-RDS step is separate and comes after the EC2 host is serving. It is described in the EC2 section. Do not run `scripts/aws_update_my_ip.sh --apply` after `allowed_cidrs` is emptied, because `--apply` passes the Mac and box CIDRs back in. `0.0.0.0/0` and `::/0` stay rejected.

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

## EC2 backend

One Amazon Linux 2023 arm64 instance in us-east-2 runs Caddy, the FastAPI process, and Redis. The scheduler stays inside the API process. There is no Postgres container and no ElastiCache. Images come from GHCR. The repository is public, so the instance pulls anonymously. RDS stays the database. Eason runs `terraform apply` from `infra/aws` on his Mac. This repository does not call AWS.

Terraform adds, on top of the RDS and S3 stack:

- `instance_type` default `t4g.small`. The AMI is the SSM public parameter `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64`.
- A 30 GB encrypted gp3 root (`root_volume_gb`). IMDSv2 is required. Hop limit is 2 so the container can use the instance role.
- An Elastic IP (`terraform output eip`) and the instance id (`terraform output instance_id`).
- The existing `sportslab-app` security group. TCP 80 and 443 are open to the internet. TCP 22 is closed unless `enable_ssh = true`, and then only from `allowed_cidrs`. 8000 and 6379 are not published.
- An instance role (`terraform output instance_role_arn`). Managed policies are `AmazonSSMManagedInstanceCore` and `CloudWatchAgentServerPolicy`. S3 is the same prefix policy as the runtime user (list, get, put; no delete). SSM `GetParameter`, `GetParameters`, and `GetParametersByPath` are limited to `/sportslab/prod` and `/sportslab/prod/*`. `kms:Decrypt` is only via `ssm.<region>.amazonaws.com` and only when the encryption context parameter ARN is under `/sportslab/prod/`. No access keys are created.
- A system-status alarm that recovers the instance, a CloudWatch agent config for disk and memory, and a disk alarm at 80%. `alarm_email` empty skips the SNS topic. A non-empty value creates an email subscription that stays pending until the inbox confirms it.
- `domain` default empty. User data writes it to `/etc/sportslab/caddy.env`. Changing it later does not replace the instance. Edit that file and restart Caddy, or replace the instance on purpose.
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

Other names the app reads, same prefix: `DATABASE_URL`, `ODDS_API_KEY`, `OPENAI_API_KEY`, `SPORTSDATA_API_KEY`, `BALLDONTLIE_API_KEY`, `BOT_API_KEYS`, `BOT_API_KEYS_PREMIUM`, `CORS_ALLOWED_ORIGINS`, `CORS_ALLOWED_ORIGIN_REGEX`. `DATABASE_URL` must use `sslmode=verify-full` and `sslrootcert=/app/certs/global-bundle.pem`. User data downloads that public bundle to `/opt/sportslab/certs/global-bundle.pem` and compose mounts it there.

`deploy/pull-ssm-env.sh` writes `/etc/sportslab/backend.env` mode 600. It does not print values. `GHCR_PULL_USER` and `GHCR_PULL_TOKEN`, if present, go to `/etc/sportslab/ghcr.env` instead, also mode 600, and are used only when the GHCR package is private.

To rotate `VERCEL_PROXY_SECRET`: write the new value to SSM, run `deploy/pull-ssm-env.sh` on the host and `docker compose up -d` so the backend reloads it, then set the same value in Vercel and redeploy the frontend. While the two sides differ, the header does not match, so rate limits use the socket peer (one shared bucket). That is stricter, not a bypass. Do not put the new value in git or chat.

### First deploy

1. Apply the Terraform stack. Read `eip`, `instance_id`, and `instance_role_arn`.
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

`remote-up.sh` pulls `/sportslab/prod/*`, pulls the GHCR image, and starts compose. It prints `healthy` after `http://127.0.0.1/api/health` succeeds. It does not print secrets.

5. In the Vercel project, set `BACKEND_API_URL` to `http://<eip>` with no path. That is the stable origin the rewrite calls.

### Plain HTTP until a domain exists

`domain` is empty, so Caddy serves `http://:80` and reverse-proxies to the backend. There is no TLS certificate on a bare IP. Vercel's server-side rewrite to `http://<eip>` is unencrypted. The proxy secret header travels on that hop too. This is an accepted known risk until a hostname exists. Do not treat the header as hidden from the network path.

### Switching to a domain

1. Create a DNS A record for the hostname pointing at `terraform output -raw eip`.
2. Set `domain` in `terraform.tfvars` to that bare hostname (no `https://`).
3. On the instance, set `DOMAIN=` in `/etc/sportslab/caddy.env` to the same hostname. User data writes this file only on first boot.
4. `docker compose -f deploy/docker-compose.prod.yml up -d` so Caddy reloads. With `DOMAIN` set, Caddy uses automatic HTTPS on 443 and answers on 80. Ports 80 and 443 are already open.
5. Change Vercel `BACKEND_API_URL` to `https://<domain>` with no path.

### Cutover order

1. Apply the SPO-132 stack (RDS and S3), then this EC2 change in the same `infra/aws` directory.
2. Run the RDS migration in the section above. The Mac and the box can still open 5432.
3. Deploy the EC2 host and point Vercel `BACKEND_API_URL` at `http://<eip>`. Confirm `/api/health` and a real read against RDS.
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

Vercel calls this API from its own egress addresses. slowapi no longer keys only on that address. If `VERCEL_PROXY_SECRET` is non-empty and `x-sportslab-proxy-secret` matches it, the key is `x-real-ip`, or else the left-most `x-forwarded-for` entry, after `ipaddress` accepts it. Any other case uses the socket peer. Caddy does not set `trusted_proxies`, so it replaces `X-Forwarded-For` with the TCP peer it actually saw. uvicorn runs with `--proxy-headers` and `--forwarded-allow-ips` set to Caddy's address `172.30.133.10` on the pinned compose subnet `172.30.133.0/24`. It is not `*`. The backend port is not published on the host.

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
