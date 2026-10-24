output "role_arns" {
  description = "Role ARN by component (engine, cases-consumer, ...), plus deploy."
  value       = merge({ for name, role in aws_iam_role.this : name => role.arn }, { deploy = aws_iam_role.deploy.arn })
}

output "powerbi_user" {
  value = aws_iam_user.powerbi.name
}

output "bucket_names" {
  description = "Bucket names the roles expect (securepay-<env>-<name>-<account>)."
  value       = { for name, arn in local.bucket : name => replace(arn, "arn:${local.aws}:s3:::", "") }
}
