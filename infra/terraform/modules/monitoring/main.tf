# Metrics, logs and alarms of the platform (HU-59): one dashboard, the
# alarms of infrastructure.mdx ("Alarms and thresholds") that are not
# already next to their resource, the engine's log metrics and a saved
# Logs Insights query. Every alarm e-mails -ops-alarms.
#
#   #  Alarm (infrastructure.mdx)       Where
#   1  Engine latency p99 > 180 ms      here (engine_latency)
#   2  Default decisions > 1 %          here (engine_fallbacks, from the engine's decision lines)
#   3  Messages in a DLQ                modules/messaging (dlq_not_empty)
#   4  Oldest message > 5 minutes       here (queue_age)
#   5  Reconciliation not finished      modules/reconciliation (06:30 check, failed executions)
#   6  Load balancer 5xx > 1 %          here (engine_5xx)
#   7  Healthy engine tasks per zone    here (healthy_per_zone) and unhealthy targets (engine_unhealthy)
#   8  Database CPU and connections     here (database)
#   9  Cache refreshed by expiry        not applicable: the engine reads {rules}:version every second
#  10  Budget                           envs/dev (aws_budgets_budget)
#  11  Unpublished events               here (engine_unpublished)
#
# Plus: errors of each Lambda (the alerts Lambda has its own log alarm in
# modules/lambdas), exchange rates older than 4 days (#96 review) and the
# engine falling back to the fixed rates.

data "aws_region" "current" {}

locals {
  p         = var.name_prefix
  namespace = "SecurePay/${var.name_prefix}"
  alarm     = [var.ops_alarms_topic_arn]

  lb = { LoadBalancer = var.alb_arn_suffix }
  tg = { LoadBalancer = var.alb_arn_suffix, TargetGroup = var.target_group_arn_suffix }

  # Metric filters on the engine's log. The decision lines are bare JSON
  # (services/decision_engine/decision_service.py: every HOLD, REJECT or
  # default decision, and any decision slower than SLOW_DECISION_MS).
  engine_filters = {
    FallbackDecisions  = "{ $.event = \"decision\" && $.by_default IS TRUE }"
    HeldOrRejected     = "{ $.event = \"decision\" && ($.decision = \"HOLD\" || $.decision = \"REJECT\") }"
    SlowDecisions      = "{ $.event = \"decision\" && $.elapsed_ms >= ${var.slow_decision_ms} }"
    UnpublishedEvents  = "\"EVENTO_NO_PUBLICADO\""
    FixedExchangeRates = "\"using the fixed\""
  }

  # The alerts Lambda catches each job's error, so its Errors metric stays
  # at 0: modules/lambdas alarms on its ERROR lines instead.
  lambdas_with_error_alarm = { for name, function in var.lambda_function_names : name => function if name != "alerts" }
}

resource "aws_cloudwatch_log_metric_filter" "engine" {
  for_each = var.engine_deployed ? local.engine_filters : {}

  name           = "${local.p}-engine-${each.key}"
  log_group_name = var.engine_log_group_name
  pattern        = each.value

  metric_transformation {
    name          = each.key
    namespace     = local.namespace
    value         = "1"
    default_value = "0"
  }
}

# --- the engine ---------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "engine" {
  # A filtered for, not a conditional: the alarms differ in their dimensions,
  # and both branches of a conditional must have the same type.
  for_each = { for name, alarm in {
    latency = {
      description = "Alarm 1: the engine's p99 (load balancer TargetResponseTime) is above ${var.latency_p99_seconds * 1000} ms for 5 minutes; the limit is 200 ms. Check the cache latency, the CPU of the tasks and whether autoscaling is adding tasks."
      metric      = "TargetResponseTime"
      stat        = "p99"
      dimensions  = local.tg
      period      = 60
      periods     = 5
      threshold   = var.latency_p99_seconds
    }
    unhealthy = {
      description = "Alarm 7: an engine task fails its /health check behind the load balancer for 3 minutes. Check the ECS service events and the task's log."
      metric      = "UnHealthyHostCount"
      stat        = "Maximum"
      dimensions  = local.tg
      period      = 60
      periods     = 3
      threshold   = 0
    }
    unpublished = {
      description = "Alarm 11: the engine logged EVENTO_NO_PUBLICADO: decisions that never reached SNS (cases, history and analytics miss them). The log line has the whole event: republish it once SNS works."
      metric      = "UnpublishedEvents"
      stat        = "Sum"
      dimensions  = null
      period      = 300
      periods     = 1
      threshold   = 0
    }
    fixed_rates = {
      description = "The engine is converting to USD with the fixed 2026-10-01 rates: the exchange-rates table has no rate for the day or any day before it. Invoke ${local.p}-exchange-rates and check the table."
      metric      = "FixedExchangeRates"
      stat        = "Sum"
      dimensions  = null
      period      = 300
      periods     = 1
      threshold   = 0
    }
  } : name => alarm if var.engine_deployed }

  alarm_name          = "${local.p}-engine-${replace(each.key, "_", "-")}"
  alarm_description   = each.value.description
  namespace           = each.value.dimensions == null ? local.namespace : "AWS/ApplicationELB"
  metric_name         = each.value.metric
  dimensions          = each.value.dimensions
  statistic           = startswith(each.value.stat, "p") ? null : each.value.stat
  extended_statistic  = startswith(each.value.stat, "p") ? each.value.stat : null
  period              = each.value.period
  evaluation_periods  = each.value.periods
  datapoints_to_alarm = each.value.periods
  comparison_operator = "GreaterThanThreshold"
  threshold           = each.value.threshold
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm
  ok_actions          = local.alarm

  depends_on = [aws_cloudwatch_log_metric_filter.engine]
}

# Alarms 2 and 6 are a share of the requests, so they are metric math.
resource "aws_cloudwatch_metric_alarm" "engine_share" {
  for_each = { for name, alarm in {
    fallbacks = {
      description = "Alarm 2: more than 1 % of the decisions in 5 minutes were default decisions (rules timed out or the cache did not answer). Check the cache and the engine's log."
      expression  = "IF(requests > 0, 100 * FILL(problems, 0) / requests, 0)"
      metric      = { namespace = local.namespace, name = "FallbackDecisions", dimensions = null }
    }
    errors_5xx = {
      description = "Alarm 6: more than 1 % of the requests in 5 minutes got a 5xx from the engine or the load balancer: the engine is failing, not just slow. Check the tasks and their log."
      expression  = "IF(requests > 0, 100 * (FILL(problems, 0) + FILL(elb, 0)) / requests, 0)"
      metric      = { namespace = "AWS/ApplicationELB", name = "HTTPCode_Target_5XX_Count", dimensions = local.tg }
    }
  } : name => alarm if var.engine_deployed }

  alarm_name          = "${local.p}-engine-${replace(each.key, "_", "-")}"
  alarm_description   = each.value.description
  comparison_operator = "GreaterThanThreshold"
  threshold           = 1
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm
  ok_actions          = local.alarm

  metric_query {
    id          = "share"
    expression  = each.value.expression
    label       = "Percent of requests"
    return_data = true
  }

  metric_query {
    id = "problems"
    metric {
      namespace   = each.value.metric.namespace
      metric_name = each.value.metric.name
      dimensions  = each.value.metric.dimensions
      period      = 300
      stat        = "Sum"
    }
  }

  # The load balancer's own 5xx (no healthy task to send to), only for 5xx.
  dynamic "metric_query" {
    for_each = each.key == "errors_5xx" ? ["elb"] : []

    content {
      id = metric_query.value
      metric {
        namespace   = "AWS/ApplicationELB"
        metric_name = "HTTPCode_ELB_5XX_Count"
        dimensions  = local.lb
        period      = 300
        stat        = "Sum"
      }
    }
  }

  # Requests the engine answered (the load balancer's health checks are not
  # counted): the decisions of the 5 minutes.
  metric_query {
    id = "requests"
    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "RequestCount"
      dimensions  = local.tg
      period      = 300
      stat        = "Sum"
    }
  }

  depends_on = [aws_cloudwatch_log_metric_filter.engine]
}

# Alarm 7: losing a zone must still leave enough tasks.
resource "aws_cloudwatch_metric_alarm" "healthy_per_zone" {
  for_each = var.engine_deployed ? toset(var.availability_zones) : toset([])

  alarm_name          = "${local.p}-engine-healthy-${each.key}"
  alarm_description   = "Alarm 7: fewer than ${var.min_healthy_tasks_per_zone} healthy engine tasks in ${each.key} for 3 minutes; if the other zone fails now the engine cannot take the load. Check the ECS service (desired count, events, autoscaling)."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HealthyHostCount"
  dimensions          = merge(local.tg, { AvailabilityZone = each.key })
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  comparison_operator = "LessThanThreshold"
  threshold           = var.min_healthy_tasks_per_zone
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm
  ok_actions          = local.alarm
}

# --- queues, database, Lambdas ------------------------------------------------

# Alarm 4: a consumer fell behind (its DLQ alarm is in modules/messaging).
resource "aws_cloudwatch_metric_alarm" "queue_age" {
  for_each = toset(var.queues)

  alarm_name          = "${each.key}-oldest-message"
  alarm_description   = "Alarm 4: the oldest message in ${each.key} is more than 5 minutes old: its consumer Lambda fell behind or is failing. Check its errors and its concurrency."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = each.key }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 300
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm
  ok_actions          = local.alarm
}

# Alarm 8: the db.t3.micro running out.
resource "aws_cloudwatch_metric_alarm" "database" {
  for_each = {
    cpu = {
      description = "Alarm 8: database CPU above 80 % for 15 minutes. Look for slow queries (Performance Insights) and for a consumer retrying in a loop."
      metric      = "CPUUtilization"
      stat        = "Average"
      periods     = 3
      threshold   = 80
    }
    connections = {
      description = "Alarm 8: database connections above 80 % of max_connections (${var.db_max_connections}). Lower consumer_max_concurrency or look for connections left open."
      metric      = "DatabaseConnections"
      stat        = "Maximum"
      periods     = 1
      threshold   = floor(var.db_max_connections * 0.8)
    }
  }

  alarm_name          = "${local.p}-db-${each.key}"
  alarm_description   = each.value.description
  namespace           = "AWS/RDS"
  metric_name         = each.value.metric
  dimensions          = { DBInstanceIdentifier = var.db_instance_identifier }
  statistic           = each.value.stat
  period              = 300
  evaluation_periods  = each.value.periods
  datapoints_to_alarm = each.value.periods
  comparison_operator = "GreaterThanThreshold"
  threshold           = each.value.threshold
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm
  ok_actions          = local.alarm
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = local.lambdas_with_error_alarm

  alarm_name          = "${each.value}-errors"
  alarm_description   = "The Lambda ${each.value} failed in the last 5 minutes. Open /aws/lambda/${each.value}; a queue consumer retries by itself and sends the message to its DLQ after 5 attempts."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = each.value }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm
}

# The exchange-rates Lambda runs once a day; no successful run for 4 days
# means the engine converts with rates that old (review of #96). The
# engine_fixed_rates alarm covers a table with no rate at all.
resource "aws_cloudwatch_metric_alarm" "exchange_rates_stale" {
  for_each = var.exchange_rates_deployed ? { rates = var.exchange_rates_function_name } : {}

  alarm_name          = "${local.p}-exchange-rates-stale"
  alarm_description   = "No successful run of ${each.value} in ${var.exchange_rate_max_age_days} days: the newest exchange rate is that old. Invoke it by hand and check Frankfurter and its log."
  comparison_operator = "LessThanThreshold"
  threshold           = 1
  evaluation_periods  = var.exchange_rate_max_age_days
  datapoints_to_alarm = var.exchange_rate_max_age_days
  treat_missing_data  = "missing"
  alarm_actions       = local.alarm
  ok_actions          = local.alarm

  metric_query {
    id          = "succeeded"
    expression  = "FILL(runs, 0) - FILL(failed, 0)"
    label       = "Successful runs per day"
    return_data = true
  }

  dynamic "metric_query" {
    for_each = { runs = "Invocations", failed = "Errors" }

    content {
      id = metric_query.key

      metric {
        namespace   = "AWS/Lambda"
        metric_name = metric_query.value
        dimensions  = { FunctionName = each.value }
        period      = 86400
        stat        = "Sum"
      }
    }
  }
}

# --- logs ---------------------------------------------------------------------

resource "aws_cloudwatch_query_definition" "slow_decisions" {
  count = var.engine_deployed ? 1 : 0

  name            = "${local.p}/slow-decisions"
  log_group_names = [var.engine_log_group_name]
  query_string    = <<-EOT
    fields @timestamp, transaction_id, decision, by_default, elapsed_ms, rules_triggered.0 as first_rule
    | filter event = "decision" and elapsed_ms >= ${var.slow_decision_ms}
    | sort elapsed_ms desc
    | limit 100
  EOT
}

resource "aws_cloudwatch_query_definition" "default_decisions" {
  count = var.engine_deployed ? 1 : 0

  name            = "${local.p}/default-decisions"
  log_group_names = [var.engine_log_group_name]
  query_string    = <<-EOT
    fields @timestamp, transaction_id, decision, rules_triggered.0 as rule, elapsed_ms
    | filter event = "decision" and by_default = 1
    | stats count(*) as decisions by bin(5m)
  EOT
}

# --- the dashboard ------------------------------------------------------------

locals {
  region = data.aws_region.current.name

  lambda_names = values(var.lambda_function_names)

  widgets = concat(
    [
      { title = "Engine latency (load balancer)", metrics = [
        for stat in ["p50", "p95", "p99"] : ["AWS/ApplicationELB", "TargetResponseTime", "TargetGroup", var.target_group_arn_suffix, "LoadBalancer", var.alb_arn_suffix, { stat = stat, label = stat }]
      ], annotations = { horizontal = [{ label = "200 ms (RN-01)", value = 0.2 }, { label = "Alarm 1", value = var.latency_p99_seconds }] } },
      { title = "Requests and 5xx", metrics = [
        ["AWS/ApplicationELB", "RequestCount", "TargetGroup", var.target_group_arn_suffix, "LoadBalancer", var.alb_arn_suffix, { stat = "Sum" }],
        ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "TargetGroup", var.target_group_arn_suffix, "LoadBalancer", var.alb_arn_suffix, { stat = "Sum" }],
        ["AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count", "LoadBalancer", var.alb_arn_suffix, { stat = "Sum" }],
      ] },
      { title = "Healthy engine tasks per zone", metrics = [
        for zone in var.availability_zones : ["AWS/ApplicationELB", "HealthyHostCount", "TargetGroup", var.target_group_arn_suffix, "LoadBalancer", var.alb_arn_suffix, "AvailabilityZone", zone, { stat = "Minimum", label = zone }]
      ] },
      { title = "Engine CPU and memory (%)", metrics = [
        ["AWS/ECS", "CPUUtilization", "ClusterName", var.cluster_name, "ServiceName", "engine", { stat = "Average" }],
        ["AWS/ECS", "MemoryUtilization", "ClusterName", var.cluster_name, "ServiceName", "engine", { stat = "Average" }],
      ] },
      { title = "Decisions logged by the engine", metrics = [
        for name in ["HeldOrRejected", "FallbackDecisions", "SlowDecisions", "UnpublishedEvents", "FixedExchangeRates"] : [local.namespace, name, { stat = "Sum" }]
      ] },
      { title = "Messages waiting (queues and DLQs)", metrics = concat(
        [for q in var.queues : ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", q, { stat = "Maximum" }]],
        [for q in var.queues : ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", "${q}-dlq", { stat = "Maximum" }]],
      ) },
      { title = "Age of the oldest message (s)", metrics = [
        for q in var.queues : ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", q, { stat = "Maximum" }]
      ] },
      { title = "Database", metrics = [
        ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", var.db_instance_identifier, { stat = "Average" }],
        ["AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", var.db_instance_identifier, { stat = "Maximum", yAxis = "right" }],
      ] },
    ],
    length(local.lambda_names) == 0 ? [] : [
      { title = "Lambda errors", metrics = [for f in local.lambda_names : ["AWS/Lambda", "Errors", "FunctionName", f, { stat = "Sum" }]] },
      { title = "Lambda duration p95 (ms)", metrics = [for f in local.lambda_names : ["AWS/Lambda", "Duration", "FunctionName", f, { stat = "p95" }]] },
    ],
    var.state_machine_arn == null ? [] : [
      { title = "Nightly reconciliation (executions)", metrics = [
        for name in ["ExecutionsSucceeded", "ExecutionsFailed", "ExecutionsTimedOut"] : ["AWS/States", name, "StateMachineArn", var.state_machine_arn, { stat = "Sum", period = 86400 }]
      ] },
    ],
  )
}

resource "aws_cloudwatch_dashboard" "this" {
  dashboard_name = local.p
  dashboard_body = jsonencode({
    widgets = [
      for i, w in local.widgets : {
        type   = "metric"
        x      = (i % 2) * 12
        y      = floor(i / 2) * 6
        width  = 12
        height = 6
        properties = merge({
          title   = w.title
          region  = local.region
          view    = "timeSeries"
          stacked = false
          period  = 60
          metrics = w.metrics
        }, lookup(w, "annotations", null) == null ? {} : { annotations = w.annotations })
      }
    ]
  })
}
