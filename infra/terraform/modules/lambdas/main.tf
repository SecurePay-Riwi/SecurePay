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

  # Each Lambda that reaches RDS connects with its own user (MAG-361): the
  # environment has the parameter's name, never the password, and
  # CREATE_SCHEMA=false because db-bootstrap owns the tables.
  database_common = {
    DATABASE_HOST = var.database.host
    DATABASE_PORT = tostring(var.database.port)
    DATABASE_NAME = var.database.name
    CREATE_SCHEMA = "false"
  }
  database_user = { for user in ["cases_consumer", "history_consumer", "alerts", "reconciliation", "list_loader", "analytics_export", "rules_api", "cases_api"] : user => merge(local.database_common, {
    DATABASE_USER               = user
    DATABASE_PASSWORD_PARAMETER = "${var.database.parameter_path}/${user}"
  }) }

  functions = {
    cases-consumer = {
      command     = "services.consumers.cases.handler"
      in_vpc      = true
      queue       = "cases"
      environment = merge(local.database_user["cases_consumer"], { CASE_DUE_MINUTES = tostring(var.case_due_minutes) })
    }
    history-consumer = {
      command     = "services.consumers.history.handler"
      in_vpc      = true
      queue       = "history"
      environment = local.database_user["history_consumer"]
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
      environment = merge(local.database_user["alerts"], {
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
      environment = merge(local.database_user["reconciliation"], { RECON_DATA_DIR = "s3://${var.datalake_bucket}" })
    }
    # Exports the cases and the reconciliation of the window to the raw
    # layer (HU-66, C6); a step of the nightly state machine after the store.
    analytics-export = {
      command = "services.analytics.export.handler"
      in_vpc  = true
      queue   = null
      environment = merge(local.database_user["analytics_export"], {
        ANALYTICS_DATA_DIR = "s3://${var.datalake_bucket}"
        RECON_DATA_DIR     = "s3://${var.datalake_bucket}"
      })
    }
    # Copies accounts, merchants and the restricted list from PostgreSQL
    # into the cache once a day (HU-67); the engine never reads PostgreSQL.
    list-loader = {
      command = "services.cache_loader.loader.handler"
      in_vpc  = true
      queue   = null
      environment = merge(local.database_user["list_loader"], {
        VALKEY_URL     = var.cache_url
        VALKEY_CLUSTER = "true"
      })
    }
    # The analysts' APIs behind API Gateway (modules/api). Mangum turns the
    # HTTP API event into a request for the same FastAPI app as locally.
    # The rules API publishes each catalog version to the cache itself.
    rules-api = {
      command = "services.rules_api.main.handler"
      in_vpc  = true
      queue   = null
      environment = merge(local.database_user["rules_api"], {
        VALKEY_URL     = var.cache_url
        VALKEY_CLUSTER = "true"
        # The simulation (HU-24) replays raw/decisiones and raw/labels.
        ANALYTICS_DATA_DIR = "s3://${var.datalake_bucket}"
      })
    }
    cases-api = {
      command = "services.cases_api.main.handler"
      in_vpc  = true
      queue   = null
      environment = merge(local.database_user["cases_api"], {
        EVIDENCE_BUCKET         = var.evidence_bucket
        EVIDENCE_RETENTION_DAYS = var.evidence_retention_days
      })
    }
    # Tables, component users and grants with the master user (MAG-361).
    # Invoked by Terraform below, never on a schedule.
    db-bootstrap = {
      command = "services.db_bootstrap.bootstrap.handler"
      in_vpc  = true
      queue   = null
      environment = merge(local.database_common, {
        DATABASE_USER               = var.database.master_username
        DATABASE_PASSWORD_PARAMETER = "${var.database.parameter_path}/master-password"
        DATABASE_PARAMETER_PATH     = var.database.parameter_path
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

# Runs db-bootstrap once the function exists, and again only when the
# database is new, a password changed or the image changed (grants.py may
# have new grants). A failure fails the apply. The input carries no secret;
# the result (user names and counts) is kept in the state.
resource "aws_lambda_invocation" "db_bootstrap" {
  count = local.deploy ? 1 : 0

  function_name = aws_lambda_function.this["db-bootstrap"].function_name
  input = jsonencode({
    database  = var.database.instance_resource_id
    passwords = var.database.password_versions
    image     = var.image_tag
  })
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

  # No message is read before the tables and the users exist.
  depends_on = [aws_lambda_invocation.db_bootstrap]

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

  depends_on = [aws_lambda_invocation.db_bootstrap]
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

  depends_on = [aws_lambda_invocation.db_bootstrap]
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
