resource "aws_db_parameter_group" "postgres" {
  name        = "${local.name_prefix}-pg16"
  family      = "postgres16"
  description = "PostgreSQL 16 with rds.force_ssl=1"

  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "immediate"
  }
}

resource "aws_db_instance" "postgres" {
  identifier     = "${local.name_prefix}-postgres"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.db_instance_class

  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_type          = "gp3"
  # storage_encrypted without kms_key_id uses the AWS-managed key alias/aws/rds.
  storage_encrypted = true

  db_name  = var.db_name
  username = var.master_username
  # Password lives in Secrets Manager. Terraform does not set or output it.
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.postgres.name
  publicly_accessible    = var.publicly_accessible
  multi_az               = false

  backup_retention_period = var.backup_retention_period
  backup_window           = var.backup_window
  maintenance_window      = var.maintenance_window
  copy_tags_to_snapshot   = true

  auto_minor_version_upgrade = true
  deletion_protection        = true
  skip_final_snapshot        = false
  # A fixed name collides on the second destroy while the first final snapshot
  # still exists. timestamp() is only used when the instance is deleted.
  # Colons are not legal in a snapshot identifier.
  final_snapshot_identifier = "${local.name_prefix}-postgres-final-${replace(timestamp(), ":", "-")}"

  apply_immediately = false
}
