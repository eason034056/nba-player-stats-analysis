data "aws_ssm_parameter" "al2023_arm64" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

locals {
  # sort() keeps the subnet stable across plans. Default-VPC subnets are public.
  app_subnet_id = sort(data.aws_subnets.default.ids)[0]
  # aws_eip.app is allocated on its own (domain = "vpc"), so public_ip exists
  # before the instance. user_data reads it. aws_eip_association attaches the
  # address afterwards. The EIP resource does not reference the instance, so
  # this is not a cycle. A non-empty var.domain replaces the sslip.io name.
  backend_hostname = var.domain != "" ? var.domain : "${replace(aws_eip.app.public_ip, ".", "-")}.sslip.io"
}

resource "aws_security_group_rule" "http" {
  type              = "ingress"
  security_group_id = aws_security_group.app.id
  description       = "HTTP for ACME HTTP-01 and the redirect to HTTPS"
  from_port         = 80
  to_port           = 80
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
}

resource "aws_security_group_rule" "https" {
  type              = "ingress"
  security_group_id = aws_security_group.app.id
  description       = "HTTPS for Caddy"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
}

resource "aws_security_group_rule" "ssh" {
  count = var.enable_ssh && length(var.allowed_cidrs) > 0 ? 1 : 0

  type              = "ingress"
  security_group_id = aws_security_group.app.id
  description       = "SSH from allowed_cidrs"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = var.allowed_cidrs
}

resource "aws_instance" "app" {
  ami                         = data.aws_ssm_parameter.al2023_arm64.value
  instance_type               = var.instance_type
  subnet_id                   = local.app_subnet_id
  vpc_security_group_ids      = [aws_security_group.app.id]
  iam_instance_profile        = aws_iam_instance_profile.instance.name
  associate_public_ip_address = true

  # Hop limit 2 lets the backend container read the instance role from IMDSv2.
  # The host itself still requires a token (http_tokens = required).
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_size           = var.root_volume_gb
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/../../deploy/user-data.sh.tftpl", {
    domain        = local.backend_hostname
    acme_email    = var.acme_email
    aws_region    = var.region
    cw_agent_json = file("${path.module}/../../deploy/cloudwatch-agent.json")
  })

  # A later AMI in the SSM parameter must not replace the host on its own.
  lifecycle {
    ignore_changes = [ami]
  }

  tags = {
    Name = "${local.name_prefix}-app"
  }
}

resource "aws_eip" "app" {
  domain = "vpc"
}

resource "aws_eip_association" "app" {
  instance_id   = aws_instance.app.id
  allocation_id = aws_eip.app.id
}
