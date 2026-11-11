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

# sportslab-app when project is sportslab. No ingress yet. SPO-133 attaches
# the backend EC2 instance to this group.
resource "aws_security_group" "app" {
  name        = "${local.name_prefix}-app"
  description = "Future EC2 backend. No ingress. SPO-133 attaches the instance."
  vpc_id      = data.aws_vpc.default.id

  egress {
    description = "Outbound from the future instance, including to RDS"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-rds"
  description = "PostgreSQL 5432 from the app group and optional CIDRs"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "PostgreSQL from the app security group"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  dynamic "ingress" {
    for_each = toset(var.rds_allowed_security_group_ids)
    content {
      description     = "PostgreSQL from an extra security group"
      from_port       = 5432
      to_port         = 5432
      protocol        = "tcp"
      security_groups = [ingress.value]
    }
  }

  # One rule for the whole list. An empty list omits the block, so the CIDR
  # ingress rules are gone. An inline rule with cidr_blocks = [] is invalid.
  dynamic "ingress" {
    for_each = length(var.allowed_cidrs) == 0 ? toset([]) : toset(["allowed_cidrs"])
    content {
      description = "PostgreSQL from allowed_cidrs"
      from_port   = 5432
      to_port     = 5432
      protocol    = "tcp"
      cidr_blocks = var.allowed_cidrs
    }
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
