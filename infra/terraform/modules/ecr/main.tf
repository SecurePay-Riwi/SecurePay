# One image repository per component (infrastructure.mdx, "Compute and
# ingress"). Tags are immutable, so a tag always names the same image: the
# images are tagged with the short git commit, never only "latest".

resource "aws_ecr_repository" "this" {
  for_each = toset(var.repositories)

  name                 = "${var.name_prefix}-${each.key}"
  image_tag_mutability = "IMMUTABLE"

  # Dev only: destroy also deletes the images inside.
  force_delete = var.force_delete

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each = aws_ecr_repository.this

  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last ${var.keep_images} images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.keep_images
      }
      action = { type = "expire" }
    }]
  })
}

# Lambda pulls the image with its service principal, not with the
# function's role, so the repository must allow it. Only the functions of
# this environment, by name prefix.
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

data "aws_iam_policy_document" "lambda_pull" {
  for_each = toset(var.lambda_repositories)

  statement {
    sid     = "LambdaPull"
    actions = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "aws:sourceArn"
      values   = ["arn:${data.aws_partition.current.partition}:lambda:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:function:${var.name_prefix}-*"]
    }
  }
}

resource "aws_ecr_repository_policy" "lambda_pull" {
  for_each = toset(var.lambda_repositories)

  repository = aws_ecr_repository.this[each.key].name
  policy     = data.aws_iam_policy_document.lambda_pull[each.key].json
}

# EMR Serverless also pulls with its service principal, and checks the
# image when the application is created (HU-36, the reconciliation's job).
data "aws_iam_policy_document" "emr_pull" {
  for_each = toset(var.emr_repositories)

  statement {
    sid     = "EmrServerlessPull"
    actions = ["ecr:BatchGetImage", "ecr:DescribeImages", "ecr:GetDownloadUrlForLayer"]

    principals {
      type        = "Service"
      identifiers = ["emr-serverless.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${data.aws_partition.current.partition}:emr-serverless:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:/applications/*"]
    }
  }
}

resource "aws_ecr_repository_policy" "emr_pull" {
  for_each = toset(var.emr_repositories)

  repository = aws_ecr_repository.this[each.key].name
  policy     = data.aws_iam_policy_document.emr_pull[each.key].json
}
