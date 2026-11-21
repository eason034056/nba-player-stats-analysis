# Decision — one Terraform module, two environments, two state keys

- **Ticket:** SPO-140
- **Date:** 2026-11-20
- **Status:** Accepted

## Context

`infra/aws/` is already applied. That state holds the RDS instance, its parameter group, the DB subnet group, two security groups in the default VPC, the S3 bucket, and the runtime IAM user. `local.name_prefix` is `var.project` (`sportslab`). The RDS identifier is `sportslab-postgres`. State is a gitignored local file. `versions.tf` said not to add a backend until a state bucket was chosen.

A second environment has to exist before a prod database can be seeded from a dev snapshot. The EC2, OIDC, and SSM work is on the unmerged branch for #64. That branch defaults SSM to `/sportslab/prod/` and hardcodes the same prefix in the instance policy. The path says prod. The stack it will attach to is the one already applied, which is dev.

Eason runs plan and apply on his Mac. This change does not call AWS.

## Decision

Add `variable "environment"`, limited to `dev` or `prod`, default `dev`.

`local.name_prefix` stays `var.project` when `environment` is `dev`. It becomes `${var.project}-${var.environment}` only for `prod` (`sportslab-prod`). `bucket_name` stays a variable. This PR does not set a prod bucket name and does not add a prod tfvars file.

Provider `default_tags` are `merge(var.tags, { Environment = var.environment })`. `Project` and `ManagedBy` stay in `var.tags`. `Environment` is applied last so a tfvars file that only repeats those two keys cannot drop it. Tag changes on the applied resources are in place. The default VPC is a data source. `default_tags` do not tag data sources, and this module still has no `aws_vpc` resource.

State is one S3 key per environment, not a Terraform workspace:

- dev: `sportslab/dev/aws.tfstate`
- prod: `sportslab/prod/aws.tfstate`

A backend block cannot interpolate `var.environment`, so the key is a literal in a `-backend-config` file. `backend-dev.hcl.example` and `backend-prod.hcl.example` are those files. The `backend "s3" {}` block in `versions.tf` stays commented. An active block would make `terraform init` require the bucket and would break the local state already on the Mac.

Remote state is adopted later, by Eason, and only for the current stack:

1. Create or reuse a state bucket in `us-east-2`. It is not the data bucket (`var.bucket_name`). Turn on versioning, SSE-S3, and Block Public Access.
2. Copy `backend-dev.hcl.example` to gitignored `backend-dev.hcl` and set `bucket`.
3. Uncomment `backend "s3" {}` in the working copy.
4. From `infra/aws`, run `terraform init -migrate-state -backend-config=backend-dev.hcl`.
5. Accept the copy only if the destination key is `sportslab/dev/aws.tfstate`.

Do not pass `backend-prod.hcl` to that migrate. Do not commit the uncommented block until that migrate has succeeded; until the bucket exists, an active block breaks `terraform init` for every other checkout. Leave the uncomment uncommitted if the bucket is not ready.

SSM is not in this module. The parameter path for this design is `/sportslab/${environment}/`. The applied stack's path is `/sportslab/dev/`. Parameters that already exist under `/sportslab/prod/` are the dev stack under the wrong prefix. Copy them before deleting them. Do not print values.

1. List names only:

```bash
aws ssm get-parameters-by-path \
  --path /sportslab/prod/ \
  --recursive \
  --region us-east-2 \
  --query 'Parameters[].Name' \
  --output text
```

2. For each name, copy to the same suffix under `/sportslab/dev/`. Omit `--key-id` so the default `aws/ssm` key is used. Do not `echo` the value and do not run the shell with trace (`set -x`).

```bash
name="/sportslab/prod/REPLACE_WITH_PARAMETER_SUFFIX"
dest="/sportslab/dev/REPLACE_WITH_PARAMETER_SUFFIX"
value="$(aws ssm get-parameter --name "$name" --with-decryption --region us-east-2 --query Parameter.Value --output text)"
aws ssm put-parameter --name "$dest" --type SecureString --value "$value" --region us-east-2
unset value
```

3. After the #64 follow-up points the instance at `/sportslab/dev/`, confirm a read by count, not by value:

```bash
aws ssm get-parameters-by-path \
  --path /sportslab/dev/ \
  --recursive \
  --with-decryption \
  --region us-east-2 \
  --query 'length(Parameters)' \
  --output text
```

4. Delete the old `/sportslab/prod/` parameters only after that read succeeds.

Prod RDS is not created here. When it is:

1. Initialize an empty prod state only after `backend "s3" {}` is uncommented. `-backend-config` is ignored while that line is a comment. Use a separate `TF_DATA_DIR` so the dev backend in `infra/aws` is not retargeted. `terraform init -reconfigure` in the same data dir would point the next plan at the prod key.
2. Use a gitignored tfvars with `environment = "prod"` and a new `bucket_name`. Do not commit it. Do not apply that file against the dev state. The name change would plan a replacement of `sportslab-postgres`.
3. In `us-east-2`, snapshot the dev instance (`rds:CreateDBSnapshot`) or copy an automated snapshot (`rds:CopyDBSnapshot`). Restore that snapshot to a new instance (`rds:RestoreDBInstanceFromDBSnapshot`) whose identifier is `sportslab-prod-postgres`. Same region, so this is not a cross-region copy. There is no second Ball Don't Lie backfill.
4. `terraform import aws_db_instance.postgres sportslab-prod-postgres` into the prod state. Then plan. The prod security groups, subnet group, parameter group, bucket, and IAM user are creates. If the plan wants to replace the imported instance, stop.
5. The operator also needs the read and write actions this module already uses (`rds:Describe*`, create and modify for the parameter group, subnet group, and instance, tag changes, and the S3 and IAM actions in `infra/aws/README.md`). No account id belongs in this repo.

## Why this and not the alternatives

- **Suffix `dev` as well.** `sportslab-dev-postgres` is a new identifier. `identifier`, security group `name`, subnet group `name`, and parameter group `name` force a new resource. The applied database would be replaced. Tags do not.
- **A Terraform workspace per environment.** The workspace selects state. It does not select the tfvars. `workspace select prod` with the dev tfvars still open applies prod names onto the wrong state, or dev names onto the prod state. Two backend keys make that a separate file that has to be passed on purpose.
- **An active `backend "s3"` block in this PR.** `terraform init` would stop asking for a bucket that does not exist yet, and the local state would no longer load. The commented block plus the example files is the same design without that break.
- **One backend key and a different bucket per environment.** The brief's key is `sportslab/${environment}/aws.tfstate`. One state bucket and two keys keeps the split in the key. The data bucket stays `var.bucket_name` and is a different bucket from the state bucket.
- **Tag the default VPC.** Nothing in this module manages that VPC. Tagging it would start managing a resource the account already depends on. `default_tags` do not apply to the data source.
- **Put SSM in this module now.** The parameters and the instance role are on #64. Copying that branch in would make the next apply of today's state try to create EC2 and OIDC resources that are not in the state.

## Consequences

- A dev plan should show in-place `Environment` tag updates and no replacement of the RDS instance, the S3 bucket, or the VPC. This change did not run plan. Eason runs it with his own profile.
- Prod does not exist until the snapshot restore and a separate state are applied. Vercel Preview should use the dev backend. Vercel Production should not use the dev backend until that prod stack exists.
- #64, after this is on `dev`, has to stop treating `/sportslab/prod/` as the path for the applied stack. The follow-up list is in `docs/task-summaries/SPO-140-terraform-environments.md`.
