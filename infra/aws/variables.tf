variable "region" {
  type        = string
  default     = "us-east-2"
  description = "AWS region for RDS and S3. Default us-east-2 (Ohio). Use us-east-1 only if the backend host is in Virginia."

  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]$", var.region))
    error_message = "region must look like us-east-2."
  }
}

variable "project" {
  type        = string
  default     = "sportslab"
  description = "Short name used in resource names (RDS identifier, security group, parameter group, runtime IAM user)."

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.project))
    error_message = "project must be 2-21 chars, start with a letter, and contain only lowercase letters, digits, and hyphens."
  }
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to supported resources via provider default_tags."
  default = {
    Project   = "sportslab"
    ManagedBy = "terraform"
  }
}

variable "allowed_cidrs" {
  type        = list(string)
  description = "IPv4 CIDRs allowed to open TCP 5432 to RDS. No default: set the box egress /32 and the backend egress /32. 0.0.0.0/0 is rejected."

  validation {
    condition = length(var.allowed_cidrs) > 0 && alltrue([
      for cidr in var.allowed_cidrs :
      can(cidrhost(cidr, 0)) && cidr != "0.0.0.0/0" && cidr != "::/0" && !strcontains(cidr, ":")
    ])
    error_message = "allowed_cidrs must be one or more IPv4 CIDRs and must not contain 0.0.0.0/0 or ::/0."
  }
}

variable "bucket_name" {
  type        = string
  description = "Globally unique S3 bucket name, for example sportslab-data-<account-id>-<region>. No default."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.bucket_name))
    error_message = "bucket_name must be a valid S3 bucket name (3-63 chars, lowercase, digits, dots, hyphens)."
  }
}

variable "db_instance_class" {
  type        = string
  default     = "db.t4g.micro"
  description = "RDS instance class. Single-AZ db.t4g.micro is the planned size."

  validation {
    condition     = can(regex("^db\\.[a-z0-9]+\\.[a-z0-9]+$", var.db_instance_class))
    error_message = "db_instance_class must look like db.t4g.micro."
  }
}

variable "engine_version" {
  type        = string
  default     = "16.15"
  description = "RDS PostgreSQL 16.x version. 16.15 was the newest 16.x on RDS as of 2026-08-25. Confirm with `aws rds describe-db-engine-versions --engine postgres --engine-version 16` before apply, and change this if AWS has a newer 16 minor."

  validation {
    condition     = can(regex("^16(\\.[0-9]+)?$", var.engine_version))
    error_message = "engine_version must be a PostgreSQL 16.x version such as 16.15."
  }
}

variable "allocated_storage" {
  type        = number
  default     = 20
  description = "RDS gp3 storage in GB. 20 is the minimum."

  validation {
    condition     = var.allocated_storage >= 20
    error_message = "allocated_storage must be at least 20 GB."
  }
}

variable "max_allocated_storage" {
  type        = number
  default     = 50
  description = "RDS storage autoscaling ceiling in GB."

  validation {
    condition     = var.max_allocated_storage >= var.allocated_storage
    error_message = "max_allocated_storage must be greater than or equal to allocated_storage."
  }
}

variable "backup_retention_period" {
  type        = number
  default     = 7
  description = "RDS automated backup retention in days."

  validation {
    condition     = var.backup_retention_period >= 1 && var.backup_retention_period <= 35
    error_message = "backup_retention_period must be between 1 and 35 days."
  }
}

variable "pg_dump_retention_days" {
  type        = number
  default     = 90
  description = "Days to keep current objects under pg-dumps/ before S3 expires them."

  validation {
    condition     = var.pg_dump_retention_days >= 1
    error_message = "pg_dump_retention_days must be at least 1."
  }
}

variable "ia_transition_days" {
  type        = number
  default     = 30
  description = "Days before current objects larger than 128 KB transition to Standard-IA."

  validation {
    condition     = var.ia_transition_days >= 30
    error_message = "ia_transition_days must be at least 30 (Standard-IA minimum)."
  }
}

variable "archive_transition_days" {
  type        = number
  default     = 90
  description = "Days before current objects larger than 128 KB transition to archive_storage_class."

  validation {
    condition     = var.archive_transition_days > var.ia_transition_days
    error_message = "archive_transition_days must be greater than ia_transition_days."
  }
}

variable "archive_storage_class" {
  type        = string
  default     = "GLACIER_IR"
  description = "Glacier class for the 90-day transition. GLACIER_IR is Glacier Instant Retrieval. Set GLACIER for Flexible Retrieval."

  validation {
    condition     = contains(["GLACIER_IR", "GLACIER", "DEEP_ARCHIVE"], var.archive_storage_class)
    error_message = "archive_storage_class must be GLACIER_IR, GLACIER, or DEEP_ARCHIVE."
  }
}

variable "noncurrent_expiration_days" {
  type        = number
  default     = 30
  description = "Days before noncurrent object versions expire."

  validation {
    condition     = var.noncurrent_expiration_days >= 1
    error_message = "noncurrent_expiration_days must be at least 1."
  }
}

variable "master_username" {
  type        = string
  default     = "sportslab_admin"
  description = "RDS master username. The password is managed in Secrets Manager (manage_master_user_password). Do not put the password in Terraform."

  validation {
    condition     = can(regex("^[a-zA-Z][a-zA-Z0-9_]{0,62}$", var.master_username))
    error_message = "master_username must start with a letter and contain only letters, digits, and underscores."
  }
}

variable "db_name" {
  type        = string
  default     = "novig_nba"
  description = "Initial database name created with the instance."

  validation {
    condition     = can(regex("^[a-zA-Z][a-zA-Z0-9_]{0,62}$", var.db_name))
    error_message = "db_name must start with a letter and contain only letters, digits, and underscores."
  }
}

variable "publicly_accessible" {
  type        = bool
  default     = true
  description = "Give the RDS instance a public endpoint. Ingress is still limited to allowed_cidrs. Set false only when clients share the VPC."
}

variable "maintenance_window" {
  type        = string
  default     = "tue:09:00-tue:10:00"
  description = "RDS weekly maintenance window in UTC (ddd:hh24:mi-ddd:hh24:mi). Tuesday 09:00-10:00 UTC is outside NBA game hours."
}

variable "backup_window" {
  type        = string
  default     = "07:00-08:00"
  description = "RDS daily backup window in UTC (hh24:mi-hh24:mi). Must not overlap maintenance_window."
}
