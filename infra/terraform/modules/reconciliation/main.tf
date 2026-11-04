# The nightly reconciliation with the payment partners (HU-36, RN-10):
#
#   Scheduler 02:00 Bogota -> Step Functions securepay-<env>-reconciliation
#     1. ReadStatements   Lambda statement-reader   (ingest.handler)
#     2. MatchWithSpark   AWS Glue Spark job         (match.main)
#     3. SaveDifferences  Lambda difference-writer  (store.handler)
#     4. NotifyTreasury   SNS business-alerts, audience = treasury
#
# Each step retries on its own. The machine stops after timeout_seconds
# (02:00 + 4 h 30 min = 06:30 Bogota), and at 06:30 the alerts Lambda checks
# that yesterday's run is DONE (services/alerts/reconciliation_check.py), so
# a run that failed, hung or never started wakes someone up before 07:00.
#
# The Spark job runs on AWS Glue 6.0 (Spark 4.1.1, Python 3.13): EMR is
# not available on AWS's free account plan and Glue is. Terraform zips our
# code (services/reconciliation and shared, without tests) and uploads it
# with the entry point, infra/spark/match_job.py; Glue installs the
# libraries of python_modules when the run starts.
#
# Nothing here exists until the Lambdas do (lambda_image_tag).

locals {
  deploy = var.enabled

  entry_point_key = "jobs/reconciliation/match_job.py"

  code_key = "jobs/reconciliation/reconciliation-code.zip"

  # services/reconciliation and shared without their tests, as match.py
  # imports them.
  code_files = concat(
    ["services/__init__.py"],
    [for f in fileset(var.repo_root, "services/reconciliation/**/*.py") : f if !strcontains(f, "/tests/")],
    [for f in fileset(var.repo_root, "shared/**/*.py") : f if !strcontains(f, "/tests/")],
  )

  # The machine lives in state_machine.json.tftpl, a JSON template, so the
  # CI validates it without AWS (services/reconciliation/tests/
  # test_state_machine.py: states, Next, End, Catch, the fields each step
  # reads). Each step retries on its own; any error ends in
  # ReconciliationFailed, which the alarm below counts.
  definition = templatefile("${path.module}/state_machine.json.tftpl", {
    timeout_seconds           = var.timeout_seconds
    statement_reader_arn      = var.statement_reader_arn
    difference_writer_arn     = var.difference_writer_arn
    match_job_name            = "${var.name_prefix}-reconciliation-match"
    datalake_bucket           = var.datalake_bucket
    business_alerts_topic_arn = var.business_alerts_topic_arn
  })
}

resource "aws_s3_object" "entry_point" {
  count = local.deploy ? 1 : 0

  bucket      = var.artifacts_bucket
  key         = local.entry_point_key
  source      = "${var.repo_root}/infra/spark/match_job.py"
  source_hash = filemd5("${var.repo_root}/infra/spark/match_job.py")
}

data "archive_file" "code" {
  count = local.deploy ? 1 : 0

  type        = "zip"
  output_path = "${path.root}/.terraform/reconciliation-code.zip"

  dynamic "source" {
    for_each = local.code_files

    content {
      content  = file("${var.repo_root}/${source.value}")
      filename = source.value
    }
  }
}

resource "aws_s3_object" "code" {
  count = local.deploy ? 1 : 0

  bucket      = var.artifacts_bucket
  key         = local.code_key
  source      = data.archive_file.code[0].output_path
  source_hash = data.archive_file.code[0].output_md5
}

# Billed per second only while a run lasts (1 minute minimum): two G.1X
# workers for a couple of minutes a night cost about a cent.
resource "aws_glue_job" "match" {
  count = local.deploy ? 1 : 0

  name              = "${var.name_prefix}-reconciliation-match"
  description       = "Matches a day of partner records with PagoSeguro's decisions (services/reconciliation/match.py)."
  role_arn          = var.glue_job_role_arn
  glue_version      = var.glue_version
  worker_type       = var.worker_type
  number_of_workers = var.workers
  timeout           = var.job_timeout_minutes
  max_retries       = 0

  command {
    name            = "glueetl"
    script_location = "s3://${var.artifacts_bucket}/${local.entry_point_key}"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"                     = "python"
    "--extra-py-files"                   = "s3://${var.artifacts_bucket}/${local.code_key}"
    "--additional-python-modules"        = var.python_modules
    "--enable-continuous-cloudwatch-log" = "true"
  }

  execution_property {
    max_concurrent_runs = 1
  }

  depends_on = [aws_s3_object.entry_point, aws_s3_object.code]
}

resource "aws_sfn_state_machine" "reconciliation" {
  count = local.deploy ? 1 : 0

  name       = "${var.name_prefix}-reconciliation"
  role_arn   = var.state_machine_role_arn
  definition = jsonencode(jsondecode(local.definition))

  depends_on = [aws_glue_job.match]

}

resource "aws_scheduler_schedule" "reconciliation" {
  count = local.deploy ? 1 : 0

  name                = "${var.name_prefix}-reconciliation"
  schedule_expression = var.schedule

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_sfn_state_machine.reconciliation[0].arn
    role_arn = var.scheduler_role_arn
    input    = jsonencode({})

    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}

# 06:30 Bogota: the alerts Lambda checks that yesterday's run is DONE and
# warns ops-alarms if not (failed, still running or never started).
resource "aws_scheduler_schedule" "check" {
  count = local.deploy ? 1 : 0

  name                = "${var.name_prefix}-reconciliation-check"
  schedule_expression = var.check_schedule

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = var.alerts_function_arn
    role_arn = var.scheduler_role_arn
    input    = jsonencode({ job = "reconciliation_check" })

    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}

# Any execution that failed, timed out (still running at 06:30) or was
# aborted. The 06:30 check also covers a run that never started.
resource "aws_cloudwatch_metric_alarm" "failed" {
  count = local.deploy ? 1 : 0

  alarm_name          = "${var.name_prefix}-reconciliation-failed"
  alarm_description   = "The nightly reconciliation failed, timed out or was aborted. Open the execution in Step Functions, fix the cause and start it again with {\"day\": \"YYYY-MM-DD\"}."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.ops_alarms_topic_arn]

  metric_query {
    id          = "problems"
    expression  = "FILL(failed, 0) + FILL(timed_out, 0) + FILL(aborted, 0)"
    label       = "Failed, timed out or aborted executions"
    return_data = true
  }

  dynamic "metric_query" {
    for_each = { failed = "ExecutionsFailed", timed_out = "ExecutionsTimedOut", aborted = "ExecutionsAborted" }

    content {
      id = metric_query.key

      metric {
        namespace   = "AWS/States"
        metric_name = metric_query.value
        dimensions  = { StateMachineArn = aws_sfn_state_machine.reconciliation[0].arn }
        period      = 300
        stat        = "Sum"
      }
    }
  }
}
