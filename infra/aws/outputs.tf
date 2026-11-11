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
  description = "Id of the app security group. SPO-133 attaches the backend EC2 instance to it. The group has no ingress rules. RDS allows TCP 5432 from this id."
  value       = aws_security_group.app.id
}

output "vpc_id" {
  description = "VPC of the security groups and the RDS subnet group. The default VPC when var.vpc_id is null."
  value       = local.vpc_id
}

output "public_subnet_ids" {
  description = "Subnet ids in that VPC with MapPublicIpOnLaunch true. SPO-133 places the backend EC2 instance in one of these."
  value       = local.public_subnet_ids
}

output "runtime_s3_policy_json" {
  description = "Runtime IAM policy (Get/Put/List on the four prefixes, no delete). Access keys are not created here."
  value       = data.aws_iam_policy_document.runtime.json
}
