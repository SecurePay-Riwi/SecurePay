output "decisions_topic_arn" {
  value = aws_sns_topic.decisions.arn
}

output "business_alerts_topic_arn" {
  value = aws_sns_topic.business_alerts.arn
}

output "ops_alarms_topic_arn" {
  value = aws_sns_topic.ops_alarms.arn
}

output "queue_arns" {
  description = "Queue ARN by consumer: cases, history, analytics."
  value       = { for name, queue in aws_sqs_queue.this : name => queue.arn }
}

output "dlq_urls" {
  value = { for name, queue in aws_sqs_queue.dlq : name => queue.id }
}
