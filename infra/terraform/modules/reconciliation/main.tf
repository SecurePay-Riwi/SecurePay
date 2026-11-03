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

  decisions_path = "s3://${var.datalake_bucket}/raw/decisiones"
  # The same folder match_dir() builds in services/reconciliation/__init__.py.
  match_path = "States.Format('s3://${var.datalake_bucket}/curated/conciliacion/fecha={}', $.ingest.day)"

  code_key = "jobs/reconciliation/reconciliation-code.zip"

  # services/reconciliation and shared without their tests, as match.py
  # imports them.
  code_files = concat(
    ["services/__init__.py"],
    [for f in fileset(var.repo_root, "services/reconciliation/**/*.py") : f if !strcontains(f, "/tests/")],
    [for f in fileset(var.repo_root, "shared/**/*.py") : f if !strcontains(f, "/tests/")],
  )

  # Lambda's own transient errors and a failed run of the step: twice more,
  # 1 and 2 minutes later.
  lambda_retry = [{
    ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException", "States.TaskFailed"]
    IntervalSeconds = 60
    MaxAttempts     = 2
    BackoffRate     = 2
  }]

  on_error = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "ReconciliationFailed" }]

  definition = {
    Comment        = "Nightly reconciliation: read the partners' files, match them with Spark, save the differences, tell treasury."
    TimeoutSeconds = var.timeout_seconds
    StartAt        = "ReadStatements"
    States = {
      # Input {} (the schedule: yesterday in Bogota) or {"day": "YYYY-MM-DD"}.
      ReadStatements = {
        Type       = "Task"
        Resource   = "arn:aws:states:::lambda:invoke"
        Parameters = { FunctionName = var.statement_reader_arn, "Payload.$" = "$" }
        ResultSelector = {
          "day.$"          = "$.Payload.day"
          "records_path.$" = "$.Payload.records_path"
          "files_read.$"   = "$.Payload.files_read"
          "records.$"      = "$.Payload.records"
          "rejected.$"     = "$.Payload.rejected"
        }
        ResultPath = "$.ingest"
        Retry      = local.lambda_retry
        Catch      = local.on_error
        Next       = "MatchWithSpark"
      }

      MatchWithSpark = {
        Type     = "Task"
        Resource = "arn:aws:states:::glue:startJobRun.sync"
        Parameters = {
          JobName = one(aws_glue_job.match[*].name)
          Arguments = {
            "--day.$"     = "$.ingest.day"
            "--records.$" = "$.ingest.records_path"
            "--decisions" = local.decisions_path
            "--output.$"  = local.match_path
          }
        }
        ResultPath = null
        Retry = [{
          ErrorEquals     = ["States.TaskFailed"]
          IntervalSeconds = 120
          MaxAttempts     = 1
          BackoffRate     = 2
        }]
        Catch = local.on_error
        Next  = "SaveDifferences"
      }

      SaveDifferences = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = var.difference_writer_arn
          Payload = {
            "day.$"        = "$.ingest.day"
            "match_path.$" = local.match_path
            "files_read.$" = "$.ingest.files_read"
            "records.$"    = "$.ingest.records"
            "rejected.$"   = "$.ingest.rejected"
          }
        }
        ResultSelector = {
          "matched.$"         = "$.Payload.matched"
          "differences.$"     = "$.Payload.differences"
          "new_differences.$" = "$.Payload.new_differences"
        }
        ResultPath = "$.store"
        Retry      = local.lambda_retry
        Catch      = local.on_error
        Next       = "NotifyTreasury"
      }

      # Treasury needs the day's result and the pending differences
      # (assignment, actors). The details are in the cases API.
      NotifyTreasury = {
        Type     = "Task"
        Resource = "arn:aws:states:::sns:publish"
        Parameters = {
          TopicArn    = var.business_alerts_topic_arn
          "Subject.$" = "States.Format('Reconciliation of {} done', $.ingest.day)"
          "Message.$" = "States.Format('Reconciliation of {} done. Files read: {}. Records: {}. Rejected rows: {}. Matched: {}. Differences of the day: {} (new: {}). Pending differences: GET /reconciliation/differences in the cases API.', $.ingest.day, $.ingest.files_read, $.ingest.records, $.ingest.rejected, $.store.matched, $.store.differences, $.store.new_differences)"
          MessageAttributes = {
            audience = { DataType = "String", StringValue = "treasury" }
          }
        }
        ResultPath = null
        Retry = [{
          ErrorEquals     = ["States.ALL"]
          IntervalSeconds = 30
          MaxAttempts     = 2
          BackoffRate     = 2
        }]
        Catch = local.on_error
        End   = true
      }

      ReconciliationFailed = {
        Type      = "Fail"
        Error     = "ReconciliationFailed"
        CausePath = "$.error.Cause"
      }
    }
  }
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
  definition = jsonencode(local.definition)

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
