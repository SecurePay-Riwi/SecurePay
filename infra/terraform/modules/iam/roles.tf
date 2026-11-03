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
        { Sid = "ReadExchangeRates", Effect = "Allow", Action = "dynamodb:Query", Resource = "${local.arn.table}-exchange-rates" },
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
        # The 30-day history is PostgreSQL account_transactions (team
        # decision D3, Sprint 4), not DynamoDB and the cache: it only needs
        # its queue and RDS through sg-lambda.
        { Sid = "ReadHistoryQueue", Effect = "Allow", Action = local.sqs_read, Resource = "${local.arn.queue}-history" },
      ]
    }

    analytics-consumer = {
      service = "lambda.amazonaws.com"
      statements = [
        { Sid = "ReadAnalyticsQueue", Effect = "Allow", Action = local.sqs_read, Resource = "${local.arn.queue}-analytics" },
        # One JSON Lines object per batch, as services/consumers/analytics.py
        # writes it. The queue mapping groups up to 1,000 decisions per batch
        # (modules/lambdas), so no Firehose: it is not on the free plan.
        { Sid = "WriteRawDecisions", Effect = "Allow", Action = "s3:PutObject", Resource = "${local.bucket.datalake}/raw/decisiones/*" },
      ]
    }

    rules-api = {
      service = "lambda.amazonaws.com"
      statements = [
        { Sid = "DatabasePassword", Effect = "Allow", Action = "ssm:GetParameter", Resource = "${local.arn.parameter}/rds/rules_api" },
        { Sid = "AnnounceRuleChange", Effect = "Allow", Action = "sns:Publish", Resource = "${local.arn.topic}-rule-changed" },
        # The simulation (HU-24) replays raw/decisiones with the generator's
        # labels in Python inside this Lambda: it lists the files, then reads them.
        { Sid = "FindSimulationFiles", Effect = "Allow", Action = "s3:ListBucket", Resource = local.bucket.datalake, Condition = { StringLike = { "s3:prefix" = ["raw/decisiones/*", "raw/labels/*"] } } },
        { Sid = "ReadSimulationFiles", Effect = "Allow", Action = "s3:GetObject", Resource = ["${local.bucket.datalake}/raw/decisiones/*", "${local.bucket.datalake}/raw/labels/*"] },
      ]
    }

    cases-api = {
      service = "lambda.amazonaws.com"
      statements = [
        { Sid = "DatabasePassword", Effect = "Allow", Action = "ssm:GetParameter", Resource = "${local.arn.parameter}/rds/cases_api" },
        # PutObjectRetention: archive() sets each object's own retain-until date.
        { Sid = "StoreAndReadEvidence", Effect = "Allow", Action = ["s3:PutObject", "s3:PutObjectRetention", "s3:GetObject"], Resource = "${local.bucket.evidence}/*" },
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
        # The 06:30 check warns the team when the night's reconciliation is not DONE.
        { Sid = "ReconciliationLate", Effect = "Allow", Action = "sns:Publish", Resource = "${local.arn.topic}-ops-alarms" },
        # archive_pending() retries the evidence of resolved cases (HU-32).
        { Sid = "ArchiveEvidence", Effect = "Allow", Action = ["s3:PutObject", "s3:PutObjectRetention", "s3:GetObject"], Resource = "${local.bucket.evidence}/*" },
      ]
    }

    exchange-rates = {
      service = "lambda.amazonaws.com"
      statements = [
        # store.save() writes with batch_writer(), which calls BatchWriteItem.
        { Sid = "StoreDailyRate", Effect = "Allow", Action = ["dynamodb:PutItem", "dynamodb:BatchWriteItem"], Resource = "${local.arn.table}-exchange-rates" },
      ]
    }

    list-loader = {
      service = "lambda.amazonaws.com"
      statements = [
        { Sid = "CacheWithIam", Effect = "Allow", Action = "elasticache:Connect", Resource = [local.arn.cache, "${local.arn.cache_user}-list-loader"] },
        { Sid = "DatabasePassword", Effect = "Allow", Action = "ssm:GetParameter", Resource = "${local.arn.parameter}/rds/list_loader" },
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
        # ingest.run() writes records.jsonl and rejects.jsonl (HU-36).
        { Sid = "WriteRecords", Effect = "Allow", Action = "s3:PutObject", Resource = "${local.bucket.datalake}/curated/extractos/*" },
      ]
    }

    difference-writer = {
      service = "lambda.amazonaws.com"
      statements = [
        { Sid = "FindMatchFiles", Effect = "Allow", Action = "s3:ListBucket", Resource = local.bucket.datalake, Condition = { StringLike = { "s3:prefix" = ["curated/conciliacion/*"] } } },
        { Sid = "ReadDifferences", Effect = "Allow", Action = "s3:GetObject", Resource = "${local.bucket.datalake}/curated/conciliacion/*" },
        { Sid = "DatabasePassword", Effect = "Allow", Action = "ssm:GetParameter", Resource = "${local.arn.parameter}/rds/reconciliation" },
        { Sid = "NotifyTreasury", Effect = "Allow", Action = "sns:Publish", Resource = "${local.arn.topic}-business-alerts" },
      ]
    }

    reconciliation = {
      service = "states.amazonaws.com"
      statements = [
        { Sid = "InvokeSteps", Effect = "Allow", Action = "lambda:InvokeFunction", Resource = ["${local.arn.function}-statement-reader", "${local.arn.function}-difference-writer"] },
        # The match runs on AWS Glue (EMR is not on AWS's free account plan).
        { Sid = "RunSparkJob", Effect = "Allow", Action = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns", "glue:BatchStopJobRun"], Resource = "${local.arn.glue}:job/${local.p}-reconciliation-match" },
        # The last step e-mails treasury the day's result (audience = treasury).
        { Sid = "NotifyTreasury", Effect = "Allow", Action = "sns:Publish", Resource = "${local.arn.topic}-business-alerts" },
      ]
    }

    # The reconciliation's Spark job on AWS Glue (HU-36).
    glue-jobs = {
      service = "glue.amazonaws.com"
      statements = [
        { Sid = "ReadDataLake", Effect = "Allow", Action = ["s3:GetObject", "s3:ListBucket"], Resource = [local.bucket.datalake, "${local.bucket.datalake}/*"] },
        { Sid = "WriteCurated", Effect = "Allow", Action = ["s3:PutObject", "s3:DeleteObject"], Resource = "${local.bucket.datalake}/curated/*" },
        { Sid = "ReadJobCode", Effect = "Allow", Action = "s3:GetObject", Resource = "${local.bucket.artifacts}/jobs/*" },
        { Sid = "JobLogs", Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${local.arn.log_group}/aws-glue/*" },
      ]
    }

    scheduler = {
      service = "scheduler.amazonaws.com"
      # Only schedules of this account may use it (confused deputy).
      source_account = true
      statements = [
        { Sid = "ScheduledTasks", Effect = "Allow", Action = "lambda:InvokeFunction", Resource = ["${local.arn.function}-exchange-rates", "${local.arn.function}-alerts", "${local.arn.function}-list-loader"] },
        { Sid = "Reconciliation", Effect = "Allow", Action = "states:StartExecution", Resource = "${local.arn.state_machine}-reconciliation" },
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

  policies = {
    for name, role in local.roles : name => concat(
      role.statements,
      contains(keys(local.lambda_logs), name) ? [local.lambda_logs[name]] : []
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
