# SPO-133 — EC2 backend host

- Ticket: SPO-133
- Branch: `feature/SPO-133-ec2-deploy` (from `feature/SPO-132-aws-rds-s3`, then current `origin/dev`)
- Base: `dev`
- Stack: PR #62 (SPO-132). Merge that first. Until it merges, this diff also contains its commits.

## Summary

The backend host is one EC2 instance in us-east-2, described in the existing `infra/aws` stack and started with Docker Compose. Caddy, FastAPI, and Redis run on the host. The scheduler stays in the API process. Postgres stays on RDS. Images are pulled from GHCR. Eason applies Terraform himself. Nothing here calls AWS.

Vercel rewrites share one egress address, so slowapi now trusts `x-real-ip` only when `x-sportslab-proxy-secret` matches `VERCEL_PROXY_SECRET`. Agent chat returns 504 at 100 seconds so the 120 second rewrite limit is not the thing that cuts the response.

## Changes

| Area | File | Change |
|---|---|---|
| Terraform | `infra/aws/ec2.tf`, `cloudwatch.tf`, `github_oidc.tf`, `iam.tf`, `variables.tf`, `outputs.tf`, `network.tf`, `terraform.tfvars.example`, `README.md` | t4g.small (variable), AL2023 arm64 from the SSM public AMI, 30 GB encrypted gp3, IMDSv2, Elastic IP, app security group ingress 80/443, SSH only when `enable_ssh` is true and only from `allowed_cidrs`. Instance role: SSM core, CloudWatch agent, S3 prefixes, `ssm:GetParameter(s)ByPath` and `kms:Decrypt` on `/sportslab/prod/*`. No static keys. Status-check recover alarm, disk alarm at 80%, optional `alarm_email`. GitHub OIDC deploy role is off unless `enable_github_deploy_role` is true. |
| Host | `deploy/user-data.sh.tftpl`, `deploy/cloudwatch-agent.json`, `deploy/docker-compose.prod.yml`, `deploy/Caddyfile`, `deploy/Caddyfile.https`, `deploy/caddy-entrypoint.sh`, `deploy/pull-ssm-env.sh`, `deploy/remote-up.sh` | User data installs Docker, Compose v2.29.7, the CloudWatch agent, and json-file log rotation. Compose runs Caddy, the backend (scheduler in-process, 1 GiB limit), and Redis 100mb allkeys-lru. No database container and no published 8000 or 6379. Caddy is HTTP on :80 until `DOMAIN` is set, then automatic HTTPS. Read timeout 125s and `flush_interval -1`. uvicorn trusts only Caddy at `172.30.133.10` on subnet `172.30.133.0/24`. The env script writes mode 600 and does not print values. |
| Workflow | `.github/workflows/deploy-backend.yml` | `workflow_dispatch` only. Exits before build unless `DEPLOY_ENABLED` is `true`. Builds linux/arm64 and pushes to GHCR, then SSM `AWS-RunShellScript`. OIDC role, no static keys. Push to `master` is documented and not enabled. There is no `main`. |
| API | `backend/app/settings.py`, `backend/app/main.py`, `backend/app/api/agent.py`, `backend/app/api/wnba_agent.py`, `backend/app/api/agent_deadline.py`, `backend/app/middleware/rate_limit.py`, `backend/app/middleware/event_stream.py`, `docker-compose.yml`, `env.example` | `CORS_ALLOWED_ORIGINS` with `ALLOWED_ORIGINS` as the alias, `CORS_ALLOWED_ORIGIN_REGEX` for `allow_origin_regex`, `*` rejected. `VERCEL_PROXY_SECRET` is a SecretStr. The slowapi key uses the forwarded client IP only after `hmac.compare_digest` on `x-sportslab-proxy-secret`. Agent chat 504 at 100s. Event-stream responses get `Cache-Control: no-cache, no-transform`. |
| Docs | `docs/deployment/aws.md`, `docs/deployment/aws-steps-zh-TW.md` | EC2 apply, SSM SecureString, first deploy, Session Manager, `BACKEND_API_URL=http://<EIP>`, the unencrypted hop, domain cutover, the private-RDS step with SSM port forwarding, the t4g.medium scheduler split, the proxy secret, and the cost estimate with its price-list sources. |
| Tests | `backend/tests/test_spo133_ec2.py`, `backend/tests/test_agent_chat.py` | CORS, deadline, rate-limit key and buckets, SSM env file. The existing chat endpoint test patches the deadline module. |

## Why

A 1 GiB instance is tight once Docker, Caddy, Redis, and the API share it, so the default is t4g.small and the backend container is capped at 1 GiB. Building the image on the host can exhaust that, so the image is built in GitHub Actions for arm64 and pulled. The repository is public, so GHCR can be pulled without a credential. A private package still has an SSM token path that does not print the token.

Port 22 stays closed because Session Manager is enough. The instance role is the only AWS credential on the host.

Caddy, without `trusted_proxies`, replaces `X-Forwarded-For` with the TCP peer. That peer is the Vercel egress address or a direct client. uvicorn 0.30 compares `--forwarded-allow-ips` as an exact address, so the allow list is Caddy's pinned address `172.30.133.10`, not `*` and not the subnet CIDR. The subnet is pinned so that address stays on Caddy. `x-real-ip` and `x-sportslab-proxy-secret` are not hop-by-hop, so Caddy forwards them. They are trusted only when the secret matches. An empty secret never matches.

Agent chat can run three graph passes, and a slip or board runs up to six of those in series. The model client does not impose a short timeout, so the worst case is well over 120 seconds. The route returns 504 at 100 seconds with a message that says to try one pick. Caddy waits 125 seconds for that response.

CORS `*` is rejected because a credentialed wildcard is not a configuration we want, and the Vercel rewrite does not need browser CORS. The regex exists for preview hostnames. It must not match an arbitrary origin. No check uses the Origin header as authentication.

## Tests / Verification

- Backend pytest: `cd backend && /tmp/nba-venv/bin/python -m pytest -q --tb=line` → 1324 passed, 27 skipped, 6 xfailed, 0 failed. After merging SPO-132 at 7fbbf54.
- Terraform: `terraform fmt -check -recursive` clean. `terraform init -backend=false` uses hashicorp/aws v5.100.0. `terraform validate` succeeded. No plan and no apply.
- Frontend: not exercised. Compose and the header contract are documented for the frontend rewrite.
- Integration test: SKIPPED. No AWS account and no `RUN_INTEGRATION`. The SSM script test uses a fake `aws` binary.
- Fabrication scan: PASS. This change does not mock an external odds or stats API and does not add a hand-typed response body.
- Terraform: `terraform fmt -check` and `terraform validate` after `terraform init -backend=false`. No `terraform plan` and no `terraform apply`.

## Follow-ups

- [ ] Eason applies `infra/aws` after SPO-132, stores the SecureStrings, deploys the host, and sets Vercel `BACKEND_API_URL=http://<EIP>`.
- [ ] After the host is the database client, a separate apply sets `allowed_cidrs = []` and `publicly_accessible = false`. Mac and box access then use SSM port forwarding.
- [ ] Set `DEPLOY_ENABLED`, `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`, and `EC2_INSTANCE_ID`, and apply `enable_github_deploy_role` before the workflow can deploy. Make the GHCR package public, or store a pull token in SSM.
- [ ] Add `push: branches: [master]` later if deploys should follow the default branch. Do not use `main`.
- [ ] Put the real Vercel production origin and preview regex in SSM when SPO-134 has the names.
- [ ] A domain removes the unencrypted Vercel-to-EC2 hop. Until then the proxy secret travels in clear text. That is an accepted risk.
- [ ] Splitting the scheduler is a t4g.medium change, not this host.
