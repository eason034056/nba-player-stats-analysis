output "db_endpoint" {
  description = "RDS endpoint in hostname:port form. The master password is not an output."
  value       = aws_db_instance.postgres.endpoint
}

output "master_user_secret_arn" {
  description = "Secrets Manager ARN of the RDS-managed master password. Retrieve the value in the console. Terraform does not output the password."
  value       = aws_db_instance.postgres.master_user_secret[0].secret_arn
}

output "bucket_name" {
  description = "S3 bucket name."
  value       = aws_s3_bucket.this.bucket
}

output "app_security_group_id" {
  description = "Id of the app security group. The EC2 instance is attached to it. Ingress is TCP 80 and 443, plus TCP 22 only when enable_ssh is true. RDS allows TCP 5432 from this id."
  value       = aws_security_group.app.id
}

output "instance_id" {
  description = "EC2 instance id. Session Manager and the deploy workflow use this id."
  value       = aws_instance.app.id
}

output "eip" {
  description = "Elastic IP attached to the backend. When domain is empty, backend_api_url is derived from this address. No password."
  value       = aws_eip.app.public_ip
}

output "backend_api_url" {
  description = "HTTPS origin for Vercel BACKEND_API_URL. No path and no password."
  value       = "https://${local.backend_hostname}"
}

output "instance_role_arn" {
  description = "Instance role ARN. The host has no static access keys."
  value       = aws_iam_role.instance.arn
}

output "github_deploy_role_arn" {
  description = "GitHub Actions deploy role ARN, or null when enable_github_deploy_role is false."
  value       = one(aws_iam_role.github_deploy[*].arn)
}

output "runtime_s3_policy_json" {
  description = "Runtime IAM policy (Get/Put/List on the four prefixes, no delete). Access keys are not created here."
  value       = data.aws_iam_policy_document.runtime.json
}
