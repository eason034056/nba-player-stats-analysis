# Sports Lab AWS (RDS PostgreSQL 16 + S3)

Terraform for one Single-AZ RDS PostgreSQL 16 instance and one private S3 bucket. This directory does not create resources by itself. Eason runs `terraform apply` from his own machine with his own AWS login. No access keys are created here. The master password is stored by RDS in Secrets Manager (`manage_master_user_password = true`) and is not a Terraform output.

State is local (`terraform.tfstate` in this directory). It is gitignored, as is `*.tfvars`. Commit only `terraform.tfvars.example`.

## What apply creates

- RDS PostgreSQL 16.x (`engine_version`, default `16.15`) on `db.t4g.micro`, gp3, 20 GB, autoscaling to 50 GB, Single-AZ.
- Encrypted storage with the AWS-managed key `aws/rds` (`storage_encrypted` and no `kms_key_id`).
- Automated backups kept `backup_retention_period` days (default 7), deletion protection on, final snapshot required.
- Parameter group `${project}-pg16` (`postgres16`) with `rds.force_ssl = 1`.
- Security group `${project}-rds`: inbound TCP 5432 from `allowed_cidrs` only. `0.0.0.0/0` is rejected before plan.
- S3 bucket: Block Public Access (all four), BucketOwnerEnforced, versioning, SSE-S3 (AES256), TLS-only bucket policy.
- Lifecycle: current objects larger than 128 KB move to Standard-IA after 30 days and to Glacier Instant Retrieval (`GLACIER_IR`) after 90. Noncurrent versions expire after 30 days. Incomplete multipart uploads abort after 7 days. `pg-dumps/` current objects expire after `pg_dump_retention_days` (default 90).
- Prefix objects: `bdl-raw/`, `bdl-archive/`, `bdl-samples/`, `pg-dumps/`.
- IAM user `${project}-runtime` with GetObject, PutObject, and ListBucket on those prefixes only. No `s3:DeleteObject`. No access key.

Redis stays on the local compose stack. It is not in this module.

## Before the first apply

1. Use an IAM user with MFA, not the account root. Upgrade a new account from the Free plan to the Paid plan before relying on this for data. A Free plan account can be suspended when the credit period ends.
2. Pick the region closest to the backend host. `us-east-1` and `us-east-2` have the same list prices for this set. Default is `us-east-2`.
3. In Billing, create a monthly cost budget of $25 with email alerts at 80% actual and 100% forecast.
4. Confirm the engine version:

```bash
aws rds describe-db-engine-versions --engine postgres --engine-version 16 --region us-east-2
```

If the newest available 16.x is not `16.15`, set `engine_version` in `terraform.tfvars`.

5. Copy the example variables and replace the placeholders. Use the box egress `/32` and the backend egress `/32`. Never `0.0.0.0/0`.

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
```

## Commands Eason runs

From `infra/aws`:

```bash
terraform init
terraform fmt -recursive
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
```

`terraform plan` and `terraform apply` talk to AWS. Review the plan before apply. `tfplan` is gitignored.

Read the three outputs (no secret values):

```bash
terraform output db_endpoint
terraform output master_user_secret_arn
terraform output bucket_name
terraform output runtime_s3_policy_json
```

Then:

1. Secrets Manager → open `master_user_secret_arn` → Retrieve secret value. That is the master password. Put it in the masked secret form on the box, not in chat and not in git.
2. IAM → user `sportslab-runtime` → Security credentials → Create access key → CLI. Put `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in the masked form. Terraform does not create this key, so it never lands in state.
3. Build `DATABASE_URL` as documented in `docs/deployment/aws.md`.

To change the allowlist later, edit `allowed_cidrs` and apply again. To rotate the runtime key, create a new key in the console, update the box, then delete the old key. To rotate the master password, use Secrets Manager rotation or RDS modify; do not put the new password in a `.tf` file.

Tearing the stack down is a separate decision. The provisioner policy below has no `rds:DeleteDBInstance` and no `s3:DeleteBucket`. Deletion protection is on. Eason turns those off with his own admin login if he ever wants them gone.

## Console fallback

Use this if you would rather click than run Terraform. Names match the module.

1. RDS → Parameter groups → Create. Family `postgres16`, name `sportslab-pg16`. Edit `rds.force_ssl` to `1`.
2. EC2 → Security groups → Create `sportslab-rds` in the default VPC. Inbound: PostgreSQL 5432 from the box egress `/32` (recorded 2026-11-10 as `184.193.214.44/32`; confirm the current address) and from the backend egress `/32`. No other inbound. Do not add `0.0.0.0/0`.
3. RDS → Create database → Standard create → PostgreSQL → the current 16.x (16.15 unless step 4 above shows a newer minor) → Dev/Test template → Single-AZ → `db.t4g.micro` → gp3 20 GB, autoscaling max 50 → master username `sportslab_admin` → Managed in AWS Secrets Manager → Public access Yes → security group `sportslab-rds` (remove default) → parameter group `sportslab-pg16` → backups 7 days → encryption on (aws/rds) → deletion protection on → initial database name `novig_nba` → Create.
4. S3 → Create bucket in the same region. ACLs disabled. Block all public access. Versioning enabled. Default encryption SSE-S3. Then Management → Lifecycle:
   - Objects larger than 128 KB: Standard-IA at 30 days, Glacier Instant Retrieval at 90 days.
   - Noncurrent versions expire at 30 days. Abort incomplete multipart uploads at 7 days.
   - Prefix `pg-dumps/`: expire current objects at 90 days.
   - Permissions → Bucket policy: paste the TLS deny statement from `s3.tf` (`aws:SecureTransport` = false).
   - Create empty prefix keys `bdl-raw/`, `bdl-archive/`, `bdl-samples/`, `pg-dumps/` if you want them visible before the first upload.
5. IAM → Users → Create `sportslab-runtime` → attach the inline policy in `iam.tf` (or `terraform output runtime_s3_policy_json` from a plan that has not been applied yet will not exist; copy the statement from `iam.tf` and replace the bucket name). Security credentials → Create access key (CLI) → masked secret form only.

## Provisioner policy

Preferred: Eason runs `terraform apply` with his admin login, and no provisioner key is created.

If a separate user `sportslab-provisioner` must run Terraform, attach the policy below, replace `REGION`, `ACCOUNT`, and `BUCKET`, use the key once, then delete the key. It has no delete action for the database or the bucket. The `aws:CalledVia` condition and the exact read actions Terraform needs are unverified until the first `terraform plan`. If plan fails on one missing read action, add that action and plan again.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "Describe", "Effect": "Allow", "Action": [
      "rds:Describe*", "rds:ListTagsForResource", "ec2:Describe*",
      "s3:ListAllMyBuckets", "iam:GetUser", "iam:GetPolicy", "iam:GetPolicyVersion",
      "iam:ListAttachedUserPolicies", "iam:ListUserPolicies", "iam:GetUserPolicy",
      "secretsmanager:DescribeSecret", "kms:DescribeKey", "sts:GetCallerIdentity"],
      "Resource": "*"},
    {"Sid": "RdsManage", "Effect": "Allow", "Action": [
      "rds:CreateDBInstance", "rds:ModifyDBInstance", "rds:RebootDBInstance",
      "rds:CreateDBParameterGroup", "rds:ModifyDBParameterGroup",
      "rds:CreateDBSubnetGroup", "rds:ModifyDBSubnetGroup",
      "rds:AddTagsToResource", "rds:RemoveTagsFromResource", "rds:CreateDBSnapshot"],
      "Resource": [
        "arn:aws:rds:REGION:ACCOUNT:db:sportslab-*",
        "arn:aws:rds:REGION:ACCOUNT:pg:sportslab-*",
        "arn:aws:rds:REGION:ACCOUNT:subgrp:sportslab-*",
        "arn:aws:rds:REGION:ACCOUNT:snapshot:sportslab-*"]},
    {"Sid": "RdsManagedSecret", "Effect": "Allow", "Action": [
      "secretsmanager:CreateSecret", "secretsmanager:TagResource",
      "secretsmanager:RotateSecret", "kms:Decrypt", "kms:GenerateDataKey"],
      "Resource": "*",
      "Condition": {"ForAnyValue:StringEquals": {"aws:CalledVia": ["rds.amazonaws.com"]}}},
    {"Sid": "RdsServiceLinkedRole", "Effect": "Allow", "Action": "iam:CreateServiceLinkedRole",
      "Resource": "arn:aws:iam::ACCOUNT:role/aws-service-role/rds.amazonaws.com/AWSServiceRoleForRDS",
      "Condition": {"StringEquals": {"iam:AWSServiceName": "rds.amazonaws.com"}}},
    {"Sid": "SecurityGroup", "Effect": "Allow", "Action": [
      "ec2:CreateSecurityGroup", "ec2:AuthorizeSecurityGroupIngress",
      "ec2:RevokeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupEgress", "ec2:CreateTags"],
      "Resource": "*"},
    {"Sid": "Bucket", "Effect": "Allow", "Action": [
      "s3:CreateBucket", "s3:PutBucketPublicAccessBlock", "s3:GetBucketPublicAccessBlock",
      "s3:PutBucketOwnershipControls", "s3:GetBucketOwnershipControls",
      "s3:PutBucketVersioning", "s3:GetBucketVersioning",
      "s3:PutEncryptionConfiguration", "s3:GetEncryptionConfiguration",
      "s3:PutLifecycleConfiguration", "s3:GetLifecycleConfiguration",
      "s3:PutBucketPolicy", "s3:GetBucketPolicy", "s3:PutBucketTagging", "s3:GetBucketTagging",
      "s3:GetBucket*", "s3:ListBucket", "s3:GetAccelerateConfiguration",
      "s3:GetReplicationConfiguration", "s3:GetBucketObjectLockConfiguration"],
      "Resource": "arn:aws:s3:::BUCKET"},
    {"Sid": "RuntimeUser", "Effect": "Allow", "Action": [
      "iam:CreateUser", "iam:TagUser", "iam:PutUserPolicy", "iam:DeleteUserPolicy"],
      "Resource": "arn:aws:iam::ACCOUNT:user/sportslab-runtime"}
  ]
}
```
