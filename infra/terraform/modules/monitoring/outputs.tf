output "dashboard_name" {
  value = aws_cloudwatch_dashboard.this.dashboard_name
}

output "dashboard_url" {
  description = "Open it in the console (signed in to the account)."
  value       = "https://${data.aws_region.current.name}.console.aws.amazon.com/cloudwatch/home?region=${data.aws_region.current.name}#dashboards/dashboard/${aws_cloudwatch_dashboard.this.dashboard_name}"
}

output "alarm_names" {
  description = "The alarms this module creates (the DLQ, reconciliation and alerts alarms live with their resources)."
  value = sort(concat(
    [for a in aws_cloudwatch_metric_alarm.engine : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.engine_share : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.healthy_per_zone : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.queue_age : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.database : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.lambda_errors : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.exchange_rates_stale : a.alarm_name],
  ))
}
