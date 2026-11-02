# Messaging of data-flow.mdx: the engine publishes every decision to one
# topic that copies it to three queues (fan-out), each with its DLQ; the
# alerts task e-mails through a second topic filtered by audience.
#
# Encryption: the queues use SQS-managed keys (SSE-SQS), which SNS can
# deliver to without a KMS key policy. The topics are not KMS-encrypted:
# CloudWatch alarms cannot publish to a topic under the AWS-managed SNS key.

data "aws_caller_identity" "current" {}

resource "aws_sns_topic" "decisions" {
  name = "${var.name_prefix}-decisions"
}

resource "aws_sqs_queue" "dlq" {
  for_each = toset(var.queues)

  name                      = "${var.name_prefix}-${each.key}-dlq"
  message_retention_seconds = var.dlq_retention_seconds
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "this" {
  for_each = toset(var.queues)

  name                       = "${var.name_prefix}-${each.key}"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = var.max_receive_count
  })
}

# Only the decisions topic may write to each queue.
data "aws_iam_policy_document" "from_topic" {
  for_each = aws_sqs_queue.this

  statement {
    sid       = "FromDecisionsTopic"
    actions   = ["sqs:SendMessage"]
    resources = [each.value.arn]

    principals {
      type        = "Service"
      identifiers = ["sns.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_sns_topic.decisions.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "this" {
  for_each = aws_sqs_queue.this

  queue_url = each.value.id
  policy    = data.aws_iam_policy_document.from_topic[each.key].json
}

# Raw delivery: the queue gets the engine's event, not SNS's envelope
# (services/consumers/batch.py reads the body as the event). No filters:
# every consumer sees every decision (decisions.mdx, "No subscription filters").
resource "aws_sns_topic_subscription" "queue" {
  for_each = aws_sqs_queue.this

  topic_arn            = aws_sns_topic.decisions.arn
  protocol             = "sqs"
  endpoint             = each.value.arn
  raw_message_delivery = true

  depends_on = [aws_sqs_queue_policy.this]
}

# Business alerts: one topic, each e-mail keeps only its audience
# (services/alerts/notify.py sets the attribute).
resource "aws_sns_topic" "business_alerts" {
  name = "${var.name_prefix}-business-alerts"
}

locals {
  business_emails = merge(
    { for email in var.supervisor_emails : "supervisor:${email}" => { audience = "supervisor", email = email } },
    { for email in var.compliance_emails : "compliance:${email}" => { audience = "compliance", email = email } },
  )
}

resource "aws_sns_topic_subscription" "business_email" {
  for_each = local.business_emails

  topic_arn     = aws_sns_topic.business_alerts.arn
  protocol      = "email"
  endpoint      = each.value.email
  filter_policy = jsonencode({ audience = [each.value.audience] })
}

# Operational alarms for the technical team.
resource "aws_sns_topic" "ops_alarms" {
  name = "${var.name_prefix}-ops-alarms"
}

resource "aws_sns_topic_subscription" "alarm_email" {
  for_each = toset(var.alarm_emails)

  topic_arn = aws_sns_topic.ops_alarms.arn
  protocol  = "email"
  endpoint  = each.key
}

# Any message in a DLQ means a decision that a consumer could not handle 5
# times: someone has to look at it and redrive it (infrastructure.mdx, alarms).
resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  for_each = aws_sqs_queue.dlq

  alarm_name          = "${each.value.name}-not-empty"
  alarm_description   = "Messages in ${each.value.name}: a consumer failed ${var.max_receive_count} times. Check its logs, fix the cause and redrive the DLQ."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ops_alarms.arn]
}
