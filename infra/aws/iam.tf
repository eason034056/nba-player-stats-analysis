data "aws_iam_policy_document" "runtime" {
  statement {
    sid       = "ListOurPrefixes"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.this.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      # No empty string. s3:prefix "" would allow listing the whole bucket.
      # `aws s3 ls s3://bucket/bdl-raw/` still matches `bdl-raw/*`.
      values = [for prefix in local.s3_prefixes : "${prefix}*"]
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
