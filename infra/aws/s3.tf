resource "aws_s3_bucket" "this" {
  bucket        = var.bucket_name
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket = aws_s3_bucket.this.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    id     = "transition-large-objects"
    status = "Enabled"

    filter {
      object_size_greater_than = 131072
    }

    transition {
      days          = var.ia_transition_days
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = var.archive_transition_days
      storage_class = var.archive_storage_class
    }
  }

  rule {
    id     = "expire-noncurrent-and-abort-multipart"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_expiration_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  rule {
    id     = "expire-pg-dumps"
    status = "Enabled"

    filter {
      prefix = local.pg_dumps_prefix
    }

    # Daily dumps from scripts/pg_dump_to_s3.sh. Default keeps 90 objects.
    expiration {
      days = var.pg_dump_retention_days
    }
  }

  depends_on = [aws_s3_bucket_versioning.this]
}

data "aws_iam_policy_document" "tls_only" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    actions = ["s3:*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    resources = [
      aws_s3_bucket.this.arn,
      "${aws_s3_bucket.this.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "tls_only" {
  bucket = aws_s3_bucket.this.id
  policy = data.aws_iam_policy_document.tls_only.json

  depends_on = [aws_s3_bucket_public_access_block.this]
}

resource "aws_s3_object" "prefixes" {
  for_each = local.s3_prefixes

  bucket  = aws_s3_bucket.this.id
  key     = each.value
  content = ""
}
