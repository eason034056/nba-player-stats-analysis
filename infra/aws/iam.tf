data "aws_iam_policy_document" "runtime" {
  statement {
    sid       = "ListOurPrefixes"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.this.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = concat(
        [for prefix in local.s3_prefixes : "${prefix}*"],
        [""],
      )
    }
  }

  statement {
    sid    = "ReadWriteObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = [for prefix in local.s3_prefixes : "${aws_s3_bucket.this.arn}/${prefix}*"]
  }
}

resource "aws_iam_user" "runtime" {
  name = "${local.name_prefix}-runtime"
}

resource "aws_iam_user_policy" "runtime" {
  name   = "${local.name_prefix}-runtime-s3"
  user   = aws_iam_user.runtime.name
  policy = data.aws_iam_policy_document.runtime.json
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "instance_ssm" {
  statement {
    sid    = "ReadProdParameters"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
    ]
    resources = [
      "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/sportslab/prod",
      "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/sportslab/prod/*",
    ]
  }

  # The AWS-managed aws/ssm key id is not known here. Decrypt is limited to
  # Parameter Store in this region and to parameter ARNs under /sportslab/prod/.
  statement {
    sid       = "DecryptProdParameters"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.region}.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "kms:EncryptionContext:PARAMETER_ARN"
      values = [
        "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/sportslab/prod/*",
      ]
    }
  }
}

resource "aws_iam_role" "instance" {
  name               = "${local.name_prefix}-ec2"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_instance_profile" "instance" {
  name = "${local.name_prefix}-ec2"
  role = aws_iam_role.instance.name
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "cloudwatch_agent" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_role_policy" "instance_s3" {
  name   = "${local.name_prefix}-ec2-s3"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.runtime.json
}

resource "aws_iam_role_policy" "instance_ssm" {
  name   = "${local.name_prefix}-ec2-ssm"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.instance_ssm.json
}
