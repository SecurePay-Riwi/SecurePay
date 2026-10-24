# ARNs of the resources each role may use, built from the naming convention
# (securepay-<env>-<resource>), so the roles do not depend on those
# resources existing yet. Bucket names end with the account id because S3
# names are global.

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

locals {
  account = data.aws_caller_identity.current.account_id
  region  = data.aws_region.current.name
  aws     = data.aws_partition.current.partition
  p       = var.name_prefix

  arn = {
    topic         = "arn:${local.aws}:sns:${local.region}:${local.account}:${local.p}"
    queue         = "arn:${local.aws}:sqs:${local.region}:${local.account}:${local.p}"
    table         = "arn:${local.aws}:dynamodb:${local.region}:${local.account}:table/${local.p}"
    function      = "arn:${local.aws}:lambda:${local.region}:${local.account}:function:${local.p}"
    log_group     = "arn:${local.aws}:logs:${local.region}:${local.account}:log-group:"
    repository    = "arn:${local.aws}:ecr:${local.region}:${local.account}:repository/${local.p}"
    parameter     = "arn:${local.aws}:ssm:${local.region}:${local.account}:parameter/securepay/${var.environment}"
    cache         = "arn:${local.aws}:elasticache:${local.region}:${local.account}:serverlesscache:${local.p}-cache"
    cache_user    = "arn:${local.aws}:elasticache:${local.region}:${local.account}:user:${local.p}"
    state_machine = "arn:${local.aws}:states:${local.region}:${local.account}:stateMachine:${local.p}"
    firehose      = "arn:${local.aws}:firehose:${local.region}:${local.account}:deliverystream/${local.p}"
    ecs           = "arn:${local.aws}:ecs:${local.region}:${local.account}"
    glue          = "arn:${local.aws}:glue:${local.region}:${local.account}"
    athena        = "arn:${local.aws}:athena:${local.region}:${local.account}:workgroup/${local.p}"
    role          = "arn:${local.aws}:iam::${local.account}:role/${local.p}"
    # The EMR Serverless application id is only known once it exists; until
    # then the roles are scoped to the applications of this account.
    emr_app     = "arn:${local.aws}:emr-serverless:${local.region}:${local.account}:/applications/*"
    emr_job_run = "arn:${local.aws}:emr-serverless:${local.region}:${local.account}:/applications/*/jobruns/*"
  }

  bucket = {
    datalake      = "arn:${local.aws}:s3:::${local.p}-datalake-${local.account}"
    evidence      = "arn:${local.aws}:s3:::${local.p}-evidence-${local.account}"
    list_provider = "arn:${local.aws}:s3:::${local.p}-list-provider-${local.account}"
    artifacts     = "arn:${local.aws}:s3:::${local.p}-artifacts-${local.account}"
  }

  glue_database = replace("${local.p}", "-", "_")

  # The 12 Lambdas of infrastructure.mdx; true = runs inside the VPC.
  lambdas = {
    cases-consumer      = true
    history-consumer    = true
    analytics-consumer  = false
    rules-api           = true
    cases-api           = true
    list-service        = false
    rules-cache-refresh = true
    alerts              = true
    exchange-rates      = false
    list-loader         = true
    statement-reader    = false
    difference-writer   = true
  }

  pass_emr_role = {
    Sid       = "PassRoleToEmrJob"
    Effect    = "Allow"
    Action    = "iam:PassRole"
    Resource  = "${local.arn.role}-emr-jobs"
    Condition = { StringEquals = { "iam:PassedToService" = "emr-serverless.amazonaws.com" } }
  }

  ecr_token = {
    Sid      = "EcrToken"
    Effect   = "Allow"
    Action   = "ecr:GetAuthorizationToken"
    Resource = "*" # AWS does not allow scoping this action
  }
}
