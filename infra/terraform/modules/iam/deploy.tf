# GitHub Actions deploys without stored keys: it exchanges its OIDC token for
# this role, only from the main branch of the repository.

resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # AWS validates GitHub's certificate itself; the thumbprint is required by
  # the API but no longer used for this provider.
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

locals {
  github_oidc_arn = "arn:${local.aws}:iam::${local.account}:oidc-provider/token.actions.githubusercontent.com"
  repositories    = ["engine", "generator", "admin"]
}

data "aws_iam_policy_document" "deploy_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "${local.p}-deploy"
  assume_role_policy = data.aws_iam_policy_document.deploy_trust.json

  depends_on = [aws_iam_openid_connect_provider.github]
}

resource "aws_iam_role_policy" "deploy" {
  name = "${local.p}-deploy"
  role = aws_iam_role.deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.ecr_token,
      {
        Sid      = "PushImages"
        Effect   = "Allow"
        Action   = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage"]
        Resource = [for name in local.repositories : "${local.arn.repository}-${name}"]
      },
      { Sid = "RegisterTaskDefinition", Effect = "Allow", Action = ["ecs:RegisterTaskDefinition", "ecs:DescribeTaskDefinition"], Resource = "*" }, # ECS does not scope registration
      { Sid = "DeployEngine", Effect = "Allow", Action = ["ecs:UpdateService", "ecs:DescribeServices"], Resource = "${local.arn.ecs}:service/${local.p}/engine" },
      { Sid = "RunMigrations", Effect = "Allow", Action = "ecs:RunTask", Resource = "${local.arn.ecs}:task-definition/${local.p}-admin:*" },
      { Sid = "DeployLambdas", Effect = "Allow", Action = "lambda:UpdateFunctionCode", Resource = [for name, _ in local.lambdas : "${local.arn.function}-${name}"] },
      {
        Sid       = "HandTaskRoles"
        Effect    = "Allow"
        Action    = "iam:PassRole"
        Resource  = [for name in ["engine-execution", "engine", "admin-execution", "admin"] : aws_iam_role.this[name].arn]
        Condition = { StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } }
      },
    ]
  })
}

# Power BI Desktop cannot assume roles: a read-only user, the only
# long-lived credential. Its access key is created by hand and rotated
# every 90 days; Terraform never stores it.
resource "aws_iam_user" "powerbi" {
  name = "${local.p}-powerbi"
}

resource "aws_iam_user_policy" "powerbi" {
  name = "${local.p}-powerbi"
  user = aws_iam_user.powerbi.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "RunQueries"
        Effect   = "Allow"
        Action   = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults", "athena:StopQueryExecution", "athena:GetWorkGroup"]
        Resource = "${local.arn.athena}-powerbi"
      },
      {
        Sid      = "SeeSchemas"
        Effect   = "Allow"
        Action   = ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables", "glue:GetPartitions"]
        Resource = ["${local.arn.glue}:catalog", "${local.arn.glue}:database/${local.glue_database}", "${local.arn.glue}:table/${local.glue_database}/*"]
      },
      { Sid = "ListAnalytics", Effect = "Allow", Action = "s3:ListBucket", Resource = local.bucket.datalake, Condition = { StringLike = { "s3:prefix" = ["analytics/*", "athena-results/powerbi/*"] } } },
      { Sid = "ReadAnalytics", Effect = "Allow", Action = "s3:GetObject", Resource = "${local.bucket.datalake}/analytics/*" },
      { Sid = "QueryResults", Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject"], Resource = "${local.bucket.datalake}/athena-results/powerbi/*" },
      { Sid = "ResultsBucketLocation", Effect = "Allow", Action = "s3:GetBucketLocation", Resource = local.bucket.datalake },
    ]
  })
}
