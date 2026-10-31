# One role per component with the minimum policy it needs
# (doc-website/docs/architecture/security.mdx#iam). "*" only where AWS does
# not allow scoping the action, marked with a comment.

locals {
  sqs_read = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]

  # Permissions per role, without the Lambda logs (added below).
  roles = {
    engine-execution = {
      service = "ecs-tasks.amazonaws.com"
      statements = [
        local.ecr_token,
        { Sid = "PullImage", Effect = "Allow", Action = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"], Resource = "${local.arn.repository}-engine" },
        { Sid = "OwnLogs", Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${local.arn.log_group}/ecs/${local.p}-engine:*" },
      ]
    }

    engine = {
      service = "ecs-tasks.amazonaws.com"
      statements = [
        { Sid = "PublishDecisions", Effect = "Allow", Action = "sns:Publish", Resource = "${local.arn.topic}-decisions" },
        { Sid = "CacheWithIam", Effect = "Allow", Action = "elasticache:Connect", Resource = [local.arn.cache, "${local.arn.cache_user}-engine"] },
        { Sid = "ReadExchangeRate", Effect = "Allow", Action = "dynamodb:GetItem", Resource = "${local.arn.table}-exchange-rates" },
        { Sid = "SendTraces", Effect = "Allow", Action = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"], Resource = "*" }, # X-Ray does not scope by resource
      ]
    }

    cases-consumer = {
      service = "lambda.amazonaws.com"
      statements = [
        { Sid = "ReadCasesQueue", Effect = "Allow", Action = local.sqs_read, Resource = "${local.arn.queue}-cases" },
        { Sid = "DatabasePassword", Effect = "Allow", Action = "ssm:GetParameter", Resource = "${local.arn.parameter}/rds/cases_consumer" },
      ]
    }

    history-consumer = {
      service = "lambda.amazonaws.com"
      statements = [
        { Sid = "ReadHistoryQueue", Effect = "Allow", Action = local.sqs_read, Resource = "${local.arn.queue}-history" },
        { Sid = "StoreDeviceAccount", Effect = "Allow", Action = "dynamodb:PutItem", Resource = "${local.arn.table}-device-account" },
        { Sid = "CacheWithIam", Effect = "Allow", Action = "elasticache:Connect", Resource = [local.arn.cache, "${local.arn.cache_user}-history"] },
      ]
    }

    analytics-consumer = {
      service = "lambda.amazonaws.com"
      statements = [
        { Sid = "ReadAnalyticsQueue", Effect = "Allow", Action = local.sqs_read, Resource = "${local.arn.queue}-analytics" },
        { Sid = "DeliverToFirehose", Effect = "Allow", Action = "firehose:PutRecordBatch", Resource = "${local.arn.firehose}-decisions-raw" },
      ]
    }

    firehose-raw = {
      service = "firehose.amazonaws.com"
      statements = [
        # The prefix is the one the analytics code writes (raw/decisiones/).
        { Sid = "WriteRawDecisions", Effect = "Allow", Action = ["s3:PutObject", "s3:AbortMultipartUpload"], Resource = "${local.bucket.datalake}/raw/decisiones/*" },
        { Sid = "DestinationBucket", Effect = "Allow", Action = ["s3:GetBucketLocation", "s3:ListBucket", "s3:ListBucketMultipartUploads"], Resource = local.bucket.datalake },
        { Sid = "DeliveryErrors", Effect = "Allow", Action = "logs:PutLogEvents", Resource = "${local.arn.log_group}/aws/kinesisfirehose/${local.p}-decisions-raw:*" },
      ]
    }

    rules-api = {
      service = "lambda.amazonaws.com"
      statements = [
        { Sid = "DatabasePassword", Effect = "Allow", Action = "ssm:GetParameter", Resource = "${local.arn.parameter}/rds/rules_api" },
        { Sid = "AnnounceRuleChange", Effect = "Allow", Action = "sns:Publish", Resource = "${local.arn.topic}-rule-changed" },
        { Sid = "StartSimulation", Effect = "Allow", Action = "emr-serverless:StartJobRun", Resource = local.arn.emr_app },
        { Sid = "SimulationStatus", Effect = "Allow", Action = "emr-serverless:GetJobRun", Resource = local.arn.emr_job_run },
        local.pass_emr_role,
      ]
    }

    cases-api = {
      service = "lambda.amazonaws.com"
      statements = [
        { Sid = "DatabasePassword", Effect = "Allow", Action = "ssm:GetParameter", Resource = "${local.arn.parameter}/rds/cases_api" },
        { Sid = "StoreAndReadEvidence", Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject"], Resource = "${local.bucket.evidence}/*" },
      ]
    }

    rules-cache-refresh = {
      service = "lambda.amazonaws.com"
      statements = [
        { Sid = "DatabasePassword", Effect = "Allow", Action = "ssm:GetParameter", Resource = "${local.arn.parameter}/rds/rules_reader" },
        { Sid = "CacheWithIam", Effect = "Allow", Action = "elasticache:Connect", Resource = [local.arn.cache, "${local.arn.cache_user}-rules"] },
      ]
    }

    alerts = {
      service = "lambda.amazonaws.com"
      statements = [
        { Sid = "DatabasePassword", Effect = "Allow", Action = "ssm:GetParameter", Resource = "${local.arn.parameter}/rds/alerts" },
        { Sid = "BusinessAlerts", Effect = "Allow", Action = "sns:Publish", Resource = "${local.arn.topic}-business-alerts" },
      ]
    }

    exchange-rates = {
      service = "lambda.amazonaws.com"
      statements = [
        { Sid = "StoreDailyRate", Effect = "Allow", Action = "dynamodb:PutItem", Resource = "${local.arn.table}-exchange-rates" },
      ]
    }

    list-loader = {
      service = "lambda.amazonaws.com"
      statements = [
        { Sid = "CacheWithIam", Effect = "Allow", Action = "elasticache:Connect", Resource = [local.arn.cache, "${local.arn.cache_user}-list-loader"] },
      ]
    }

    list-service = {
      service = "lambda.amazonaws.com"
      statements = [
        { Sid = "ReadProviderFile", Effect = "Allow", Action = "s3:GetObject", Resource = "${local.bucket.list_provider}/lista_restrictiva.jsonl" },
      ]
    }

    statement-reader = {
      service = "lambda.amazonaws.com"
      statements = [
        { Sid = "FindStatements", Effect = "Allow", Action = "s3:ListBucket", Resource = local.bucket.datalake, Condition = { StringLike = { "s3:prefix" = ["raw/extractos/*"] } } },
        { Sid = "ReadStatements", Effect = "Allow", Action = "s3:GetObject", Resource = "${local.bucket.datalake}/raw/extractos/*" },
      ]
    }

    difference-writer = {
      service = "lambda.amazonaws.com"
      statements = [
        { Sid = "ReadDifferences", Effect = "Allow", Action = "s3:GetObject", Resource = "${local.bucket.datalake}/curated/conciliacion/*" },
        { Sid = "DatabasePassword", Effect = "Allow", Action = "ssm:GetParameter", Resource = "${local.arn.parameter}/rds/reconciliation" },
        { Sid = "NotifyTreasury", Effect = "Allow", Action = "sns:Publish", Resource = "${local.arn.topic}-business-alerts" },
      ]
    }

    reconciliation = {
      service = "states.amazonaws.com"
      statements = [
        { Sid = "InvokeSteps", Effect = "Allow", Action = "lambda:InvokeFunction", Resource = ["${local.arn.function}-statement-reader", "${local.arn.function}-difference-writer"] },
        { Sid = "StartSparkJob", Effect = "Allow", Action = "emr-serverless:StartJobRun", Resource = local.arn.emr_app },
        { Sid = "WaitSparkJob", Effect = "Allow", Action = ["emr-serverless:GetJobRun", "emr-serverless:CancelJobRun"], Resource = local.arn.emr_job_run },
        { Sid = "JobFinishedRule", Effect = "Allow", Action = ["events:PutTargets", "events:PutRule", "events:DescribeRule"], Resource = "arn:${local.aws}:events:${local.region}:${local.account}:rule/StepFunctionsGetEventsForEMRServerlessJobRule" },
        local.pass_emr_role,
      ]
    }

    emr-jobs = {
      service = "emr-serverless.amazonaws.com"
      statements = [
        { Sid = "ReadDataLake", Effect = "Allow", Action = ["s3:GetObject", "s3:ListBucket"], Resource = [local.bucket.datalake, "${local.bucket.datalake}/*"] },
        { Sid = "WriteCuratedAndAnalytics", Effect = "Allow", Action = ["s3:PutObject", "s3:DeleteObject"], Resource = ["${local.bucket.datalake}/curated/*", "${local.bucket.datalake}/analytics/*"] },
        { Sid = "ReadJobCode", Effect = "Allow", Action = "s3:GetObject", Resource = "${local.bucket.artifacts}/jobs/*" },
        {
          Sid      = "RegisterTables"
          Effect   = "Allow"
          Action   = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:CreateTable", "glue:UpdateTable", "glue:GetPartition", "glue:GetPartitions", "glue:CreatePartition", "glue:BatchCreatePartition"]
          Resource = ["${local.arn.glue}:catalog", "${local.arn.glue}:database/${local.glue_database}", "${local.arn.glue}:table/${local.glue_database}/*"]
        },
      ]
    }

    scheduler = {
      service = "scheduler.amazonaws.com"
      # Only schedules of this account may use it (confused deputy).
      source_account = true
      statements = [
        { Sid = "ScheduledTasks", Effect = "Allow", Action = "lambda:InvokeFunction", Resource = ["${local.arn.function}-exchange-rates", "${local.arn.function}-alerts", "${local.arn.function}-list-loader"] },
        { Sid = "Reconciliation", Effect = "Allow", Action = "states:StartExecution", Resource = "${local.arn.state_machine}-reconciliation" },
        { Sid = "SparkJobs", Effect = "Allow", Action = "emr-serverless:StartJobRun", Resource = local.arn.emr_app },
        local.pass_emr_role,
      ]
    }

    admin-execution = {
      service = "ecs-tasks.amazonaws.com"
      statements = [
        local.ecr_token,
        { Sid = "PullImage", Effect = "Allow", Action = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"], Resource = "${local.arn.repository}-admin" },
        { Sid = "OwnLogs", Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${local.arn.log_group}/ecs/${local.p}-admin:*" },
        { Sid = "MasterPassword", Effect = "Allow", Action = "ssm:GetParameters", Resource = ["${local.arn.parameter}/rds/master-password", "${local.arn.parameter}/rds/master-url"] },
      ]
    }

    admin = {
      service = "ecs-tasks.amazonaws.com"
      statements = [
        { Sid = "ExportRestrictedList", Effect = "Allow", Action = "s3:PutObject", Resource = "${local.bucket.list_provider}/lista_restrictiva.jsonl" },
      ]
    }
  }

  # Lambdas outside the VPC write their own logs; the ones inside get the
  # managed AWSLambdaVPCAccessExecutionRole (network interfaces + logs).
  lambda_logs = {
    for name, in_vpc in local.lambdas : name => {
      Sid      = "OwnLogs"
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "${local.arn.log_group}/aws/lambda/${local.p}-${name}:*"
    } if !in_vpc
  }

  # Temporary, with security_groups.engine_reads_database: ECS hands the
  # engine its DATABASE_URL while the engine still reads PostgreSQL.
  temporary_database_url = {
    Sid      = "TemporaryDatabaseUrl"
    Effect   = "Allow"
    Action   = "ssm:GetParameters"
    Resource = "${local.arn.parameter}/rds/master-url"
  }

  policies = {
    for name, role in local.roles : name => concat(
      role.statements,
      contains(keys(local.lambda_logs), name) ? [local.lambda_logs[name]] : [],
      name == "engine-execution" && var.engine_reads_database ? [local.temporary_database_url] : []
    )
  }
}

data "aws_iam_policy_document" "trust" {
  for_each = local.roles

  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = [each.value.service]
    }

    dynamic "condition" {
      for_each = lookup(each.value, "source_account", false) ? [local.account] : []

      content {
        test     = "StringEquals"
        variable = "aws:SourceAccount"
        values   = [condition.value]
      }
    }
  }
}

resource "aws_iam_role" "this" {
  for_each = local.roles

  name               = "${local.p}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.trust[each.key].json
}

resource "aws_iam_role_policy" "this" {
  for_each = local.roles

  name   = "${local.p}-${each.key}"
  role   = aws_iam_role.this[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = local.policies[each.key] })
}

resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  for_each = { for name, in_vpc in local.lambdas : name => name if in_vpc }

  role       = aws_iam_role.this[each.key].name
  policy_arn = "arn:${local.aws}:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}
