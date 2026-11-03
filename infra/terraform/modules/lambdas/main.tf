# The consumers, the alerts task, the cache loader and the reconciliation
# steps as Lambdas (HU-68, HU-67, HU-36). They run the same
# image as the engine: awslambdaric is the entry point and the command is
# the handler that already exists, so there is no Lambda-only code.
#
# Nothing here exists until image_tag is set, like the engine service: the
# first apply creates the repository, the image is pushed, the next apply
# creates the functions. The exchange-rates Lambda runs another image
# (securepay-apis) and lives in exchange_rates.tf.

data "aws_region" "current" {}

locals {
  deploy = var.image_tag != null

  database = { DATABASE_URL = var.database_url }

  functions = {
    cases-consumer = {
      command     = "services.consumers.cases.handler"
      in_vpc      = true
      queue       = "cases"
      environment = merge(local.database, { CASE_DUE_MINUTES = tostring(var.case_due_minutes) })
    }
    history-consumer = {
      command     = "services.consumers.history.handler"
      in_vpc      = true
      queue       = "history"
      environment = local.database
    }
    analytics-consumer = {
      command     = "services.consumers.analytics.handler"
      in_vpc      = false
      queue       = "analytics"
      environment = { DATALAKE_BUCKET = var.datalake_bucket }
    }
    alerts = {
      command = "services.alerts.handler.handler"
      in_vpc  = true
      queue   = null
      environment = merge(local.database, {
        BUSINESS_ALERTS_TOPIC   = var.business_alerts_topic_arn
        OPS_ALARMS_TOPIC        = var.ops_alarms_topic_arn
        EVIDENCE_BUCKET         = var.evidence_bucket
        EVIDENCE_RETENTION_DAYS = var.evidence_retention_days
        CASE_DUE_MINUTES        = tostring(var.case_due_minutes)
      })
    }
    # The two Lambda steps of the nightly reconciliation (HU-36); Step
    # Functions invokes them (modules/reconciliation).
    statement-reader = {
      command = "services.reconciliation.ingest.handler"
      in_vpc  = false
      queue   = null
      environment = {
        STATEMENTS_SOURCE = "s3://${var.datalake_bucket}/raw/extractos"
        RECON_DATA_DIR    = "s3://${var.datalake_bucket}"
      }
    }
    difference-writer = {
      command     = "services.reconciliation.store.handler"
      in_vpc      = true
      queue       = null
      environment = merge(local.database, { RECON_DATA_DIR = "s3://${var.datalake_bucket}" })
    }
    # Copies accounts, merchants and the restricted list from PostgreSQL
    # into the cache once a day (HU-67); the engine never reads PostgreSQL.
    list-loader = {
      command = "services.cache_loader.loader.handler"
      in_vpc  = true
      queue   = null
      environment = merge(local.database, {
        VALKEY_URL     = var.cache_url
        VALKEY_CLUSTER = "true"
      })
    }
  }

  deployed  = local.deploy ? local.functions : {}
  consumers = { for name, f in local.deployed : name => f if f.queue != null }

  # The analytics consumer writes one S3 object per batch: large batches
  # keep the raw layer in few, big files (Firehose did this, but it is not
  # on the free plan). The other consumers keep batches of 10.
  batching = {
    analytics-consumer = { size = var.analytics_batch_size, window = var.analytics_batching_window_seconds }
  }
}

# Created before the functions, so Lambda never makes one without retention.
resource "aws_cloudwatch_log_group" "this" {
  for_each = local.deployed

  name              = "/aws/lambda/${var.name_prefix}-${each.key}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "this" {
  for_each = local.deployed

  function_name = "${var.name_prefix}-${each.key}"
  role          = var.role_arns[each.key]
  package_type  = "Image"
  image_uri     = "${var.repository_url}:${var.image_tag}"
  architectures = ["x86_64"]
  memory_size   = var.memory_mb
  timeout       = var.timeout_seconds

  image_config {
    entry_point       = ["python", "-m", "awslambdaric"]
    command           = [each.value.command]
    working_directory = "/app"
  }

  environment {
    variables = each.value.environment
  }

  dynamic "vpc_config" {
    for_each = each.value.in_vpc ? [1] : []

    content {
      subnet_ids         = var.app_subnet_ids
      security_group_ids = [var.lambda_security_group_id]
    }
  }

  # JSON logs, so the alarm below can match the level.
  logging_config {
    log_format            = "JSON"
    log_group             = aws_cloudwatch_log_group.this[each.key].name
    application_log_level = var.log_level
    system_log_level      = "WARN"
  }
}

# One mapping per queue: batches of 10 (analytics: up to
# analytics_batch_size, waiting at most analytics_batching_window_seconds),
# and only the messages listed in batchItemFailures go back to the queue
# (decisions.mdx, consumers).
resource "aws_lambda_event_source_mapping" "this" {
  for_each = local.consumers

  event_source_arn                   = var.queue_arns[each.value.queue]
  function_name                      = aws_lambda_function.this[each.key].arn
  batch_size                         = try(local.batching[each.key].size, 10)
  maximum_batching_window_in_seconds = try(local.batching[each.key].window, null)
  function_response_types            = ["ReportBatchItemFailures"]

  dynamic "scaling_config" {
    for_each = each.value.in_vpc ? [1] : []

    content {
      maximum_concurrency = var.consumer_max_concurrency
    }
  }
}

# The alerts task every 5 minutes. Scheduler invokes asynchronously; a
# failed run is not retried, the next one comes 5 minutes later and every
# job is safe to run twice.
resource "aws_lambda_function_event_invoke_config" "alerts" {
  count = local.deploy ? 1 : 0

  function_name          = aws_lambda_function.this["alerts"].function_name
  maximum_retry_attempts = 0
}

resource "aws_scheduler_schedule" "alerts" {
  count = local.deploy ? 1 : 0

  name                = "${var.name_prefix}-alerts"
  schedule_expression = var.alerts_schedule

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.this["alerts"].arn
    role_arn = var.role_arns["scheduler"]

    retry_policy {
      maximum_retry_attempts = 0
    }
  }
}

# The cache loader once a day. The keys live REFDATA_TTL_HOURS (48 h), so a
# failed night still leaves a day of margin; Scheduler retries it twice and
# the load is safe to run again.
resource "aws_scheduler_schedule" "list_loader" {
  count = local.deploy ? 1 : 0

  name                = "${var.name_prefix}-list-loader"
  schedule_expression = var.list_loader_schedule

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.this["list-loader"].arn
    role_arn = var.role_arns["scheduler"]

    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}

# The alerts handler catches each job's error (so the others still run) and
# logs it, so Lambda's Errors metric stays at 0: the alarm counts the ERROR
# lines instead. Two failing runs in a row (10 minutes) wake someone up.
resource "aws_cloudwatch_log_metric_filter" "alerts_errors" {
  count = local.deploy ? 1 : 0

  name           = "${var.name_prefix}-alerts-errors"
  log_group_name = aws_cloudwatch_log_group.this["alerts"].name
  pattern        = "{ $.level = \"ERROR\" }"

  metric_transformation {
    name          = "AlertsErrors"
    namespace     = "SecurePay/${var.name_prefix}"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "alerts_failing" {
  count = local.deploy ? 1 : 0

  alarm_name          = "${var.name_prefix}-alerts-failing"
  alarm_description   = "The alerts task logged errors in 2 runs in a row: escalations or compliance e-mails may not be going out. Check /aws/lambda/${var.name_prefix}-alerts."
  namespace           = "SecurePay/${var.name_prefix}"
  metric_name         = "AlertsErrors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.ops_alarms_topic_arn]
}
