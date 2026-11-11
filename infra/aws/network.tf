data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_db_subnet_group" "this" {
  name        = "${local.name_prefix}-rds"
  description = "Default VPC subnets for ${local.name_prefix} RDS"
  subnet_ids  = data.aws_subnets.default.ids
}

resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-rds"
  description = "PostgreSQL 5432 from allowed_cidrs only"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "PostgreSQL from the allowlist"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }

  # RDS does not accept client traffic on any other port. Egress stays open
  # so the instance can reach AWS APIs it already uses for backups.
  egress {
    description = "Allow outbound from the instance"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
