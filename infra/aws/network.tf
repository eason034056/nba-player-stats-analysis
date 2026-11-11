# vpc_id null selects the region's default VPC (default = true). A set id
# selects that VPC and leaves default unset. The provider omits a null
# argument. Setting both would require the id to also be the default VPC,
# which fails in an account that has none.
data "aws_vpc" "selected" {
  id      = var.vpc_id
  default = var.vpc_id == null ? true : null
}

data "aws_subnets" "selected" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.selected.id]
  }
}

# SPO-133 places the backend EC2 instance in one of these. The RDS subnet
# group still uses every subnet in the VPC (local.subnet_ids).
data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.selected.id]
  }

  filter {
    name   = "map-public-ip-on-launch"
    values = ["true"]
  }
}

data "aws_subnet" "selected" {
  for_each = toset(local.subnet_ids)
  id       = each.value
}

locals {
  vpc_id            = data.aws_vpc.selected.id
  subnet_ids        = data.aws_subnets.selected.ids
  public_subnet_ids = data.aws_subnets.public.ids
}

resource "aws_db_subnet_group" "this" {
  name        = "${local.name_prefix}-rds"
  description = "Subnets for ${local.name_prefix} RDS"
  subnet_ids  = local.subnet_ids

  # A lifecycle precondition does not change name, description, or subnet_ids,
  # so it does not replace a group that already exists.
  lifecycle {
    precondition {
      condition     = length(distinct([for subnet in data.aws_subnet.selected : subnet.availability_zone])) >= 2
      error_message = "The DB subnet group needs subnets in at least two availability zones. Set vpc_id to a VPC whose subnets span two AZs."
    }
  }
}

# sportslab-app when project is sportslab. The description stays as first
# applied. Egress stays inline, so Terraform keeps managing that one outbound
# rule. Ingress is not declared inline. It lives only in aws_security_group_rule
# (TCP 80, 443, and optional 22 in ec2.tf). Because this block has no ingress,
# the provider leaves those rules alone. Do not add an inline ingress block
# here. That would make this resource authoritative for ingress and remove the
# separate rules on the next apply.
resource "aws_security_group" "app" {
  name        = "${local.name_prefix}-app"
  description = "Future EC2 backend. No ingress. SPO-133 attaches the instance."
  vpc_id      = local.vpc_id

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
  vpc_id      = local.vpc_id

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
