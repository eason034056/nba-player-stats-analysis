# SPO-140 — environment-aware AWS Terraform

- Ticket: SPO-140
- Branch: `feature/SPO-140-terraform-environments` (from `dev` at `fc3f5ed`)
- Base: `dev`

## Summary

`infra/aws` can name a `dev` stack and a `prod` stack without renaming the resources already applied. `environment` defaults to `dev`. For `dev`, `local.name_prefix` stays `var.project`, so `sportslab-postgres`, `sportslab-pg16`, `sportslab-rds`, `sportslab-app`, and `sportslab-runtime` do not change. The provider adds `Environment` from that variable. Tag updates are in place. Prod would use `sportslab-prod` and a different S3 state key. The S3 backend block stays commented so `terraform init` on the existing local state still works. Nothing in this change calls AWS or runs apply.

## Changes

| Area | File | Change |
|---|---|---|
| Names | `infra/aws/variables.tf`, `infra/aws/locals.tf`, `infra/aws/terraform.tfvars.example` | `environment` is `dev` or `prod`, default `dev`. `name_prefix` is `var.project` for `dev` and `${var.project}-${var.environment}` otherwise. The example sets `environment = "dev"` and does not set a prod bucket name. |
| Tags | `infra/aws/versions.tf` | `default_tags` merge `Environment = var.environment` on top of `var.tags`. The `backend "s3" {}` block is present only as a comment. |
| State | `infra/aws/backend-dev.hcl.example`, `infra/aws/backend-prod.hcl.example`, `infra/aws/.gitignore` | Keys `sportslab/dev/aws.tfstate` and `sportslab/prod/aws.tfstate`. Real `backend-*.hcl` files are gitignored. |
| Runbook | `infra/aws/README.md`, `docs/deployment/aws.md`, `docs/deployment/aws-steps-zh-TW.md` | Dev names stay. Remote-state migrate is dev-key only. SSM copy path and prod snapshot restore are documented. #64 follow-up is listed. |
| Decision | `docs/decisions/SPO-140/decision_20261120_terraform-environments.md` | Why names, tags, state keys, and the snapshot path are split this way. |
| Tests | `backend/tests/test_spo140_terraform_environments.py` | Reads the files and evaluates `local.name_prefix`. Does not call AWS. |

`rds.tf`, `s3.tf`, `network.tf`, and `iam.tf` are unchanged. No resource address moved. No `aws_vpc` resource. `engine_version`, instance class, and storage are unchanged. No prod tfvars.

## Why

A `-dev` suffix on the applied names would be a new RDS identifier, a new security group name, a new subnet group name, and a new parameter group name. Those arguments force a new resource. The database, the bucket, and the VPC have to stay. `Environment` is a tag, and tags on those resources are not ForceNew.

A workspace would switch state without switching tfvars. Two `-backend-config` files make the prod key something you pass on purpose. The backend block stays commented because an active block breaks `terraform init` for the local state that is already applied. A backend block also cannot read `var.environment`, so the key cannot live in `versions.tf`.

SSM and EC2 stay on #64. Copying that branch here would make the next apply of today's state try to create resources that are not in it.

## Tests / Verification

- Backend pytest: `cd backend && /tmp/nba-venv/bin/python -m pytest -q --tb=line` → 1716 passed, 71 skipped, 6 xfailed, 0 failed.
- `tests/test_spo140_terraform_environments.py` and `tests/test_spo132b_optional_vpc.py`: 20 passed. Console evaluation: `environment=dev` → `sportslab`; `environment=prod` → `sportslab-prod`; `staging` is rejected.
- Frontend: not touched.
- Integration test: SKIPPED. No AWS account and no `RUN_INTEGRATION`.
- Fabrication scan: PASS. No external API response was added.
- Terraform: `terraform fmt -check -recursive` clean. `terraform init -input=false` still uses the local backend. `terraform validate` succeeded with no credentials. `terraform plan` and `terraform apply` were not run.
- Diff: `rds.tf`, `s3.tf`, `network.tf`, and `iam.tf` have no changes, so `identifier`, `bucket`, `name`, `name_prefix`, `vpc_id`, and `engine` on those resources are the same expressions as `dev` today. For `environment=dev` the name strings evaluate to today's names.

## Follow-ups

- [ ] Eason runs `cd infra/aws && AWS_PROFILE=mlds423 terraform plan` (plus any `-var-file` he already uses) and reports add / change / destroy counts. Do not paste secrets or a plan that contains ids.
- [ ] When a state bucket exists, migrate only the current state to `sportslab/dev/aws.tfstate`. Do not commit the uncommented backend block before that migrate works.
- [ ] If parameters exist under `/sportslab/prod/`, copy them to `/sportslab/dev/` as SecureString with the default `aws/ssm` key. Do not print values.
- [ ] #64, after this is on `dev`: `deploy/pull-ssm-env.sh` default path `/sportslab/dev/` (built as `/sportslab/${environment}/`); instance policy ARNs `parameter/sportslab/${environment}` and `parameter/sportslab/${environment}/*`, including the KMS condition; `docs/deployment/aws.md` and `docs/deployment/aws-steps-zh-TW.md` on that branch; EC2 `Name` stays `${local.name_prefix}-app` and must not hardcode `Environment = prod`.
- [ ] Prod RDS later: snapshot in `us-east-2`, restore to `sportslab-prod-postgres`, import into an empty prod state. No second backfill. No prod apply in this PR.
