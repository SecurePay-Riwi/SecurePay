# S3 buckets of infrastructure.mdx ("Data"). Names end with the account id
# because bucket names are global. Every bucket: versioning, encryption with
# S3 managed keys, public access blocked and requests without TLS denied.

data "aws_caller_identity" "current" {}

locals {
  buckets = {
    # Tag values: S3 accepts only letters, digits, spaces and + - = . _ : / @
    datalake      = "Data Lake: raw/ curated/ analytics/ athena-results/"
    evidence      = "Case evidence - immutable with Object Lock COMPLIANCE"
    list-provider = "Third-party restricted list file - apart from the Data Lake"
    artifacts     = "Spark job code"
  }
}

resource "aws_s3_bucket" "this" {
  for_each = local.buckets

  bucket        = "${var.name_prefix}-${each.key}-${data.aws_caller_identity.current.account_id}"
  force_destroy = var.force_destroy

  # Object Lock can only be turned on when the bucket is created.
  object_lock_enabled = each.key == "evidence"

  tags = { purpose = each.value }
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = aws_s3_bucket.this

  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "tls_only" {
  for_each = aws_s3_bucket.this

  statement {
    sid     = "DenyWithoutTls"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      each.value.arn,
      "${each.value.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "tls_only" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id
  policy = data.aws_iam_policy_document.tls_only[each.key].json

  depends_on = [aws_s3_bucket_public_access_block.this]
}

# Default retention for the evidence. The minimum AWS accepts is 1 day, so
# dev sets none and the demo object gets its own 1-hour retain-until date.
resource "aws_s3_bucket_object_lock_configuration" "evidence" {
  count = var.evidence_default_retention_years > 0 ? 1 : 0

  bucket = aws_s3_bucket.this["evidence"].id

  rule {
    default_retention {
      mode  = "COMPLIANCE"
      years = var.evidence_default_retention_years
    }
  }

  depends_on = [aws_s3_bucket_versioning.this]
}
