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

output "runtime_s3_policy_json" {
  description = "Runtime IAM policy (Get/Put/List on the four prefixes, no delete). Access keys are not created here."
  value       = data.aws_iam_policy_document.runtime.json
}
