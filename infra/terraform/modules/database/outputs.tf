output "endpoint" {
  description = "Host name of the database (inside the VPC only)."
  value       = aws_db_instance.this.address
}

output "port" {
  value = aws_db_instance.this.port
}

output "database_name" {
  value = aws_db_instance.this.db_name
}

output "master_password_parameter" {
  description = "Parameter Store name of the master password (the value is never an output)."
  value       = aws_ssm_parameter.master_password.name
}

output "component_password_parameters" {
  value = { for user, parameter in aws_ssm_parameter.component_password : user => parameter.name }
}

output "master_url_parameter_arn" {
  description = "ARN of the DATABASE_URL parameter of the master user (the value is never an output)."
  value       = aws_ssm_parameter.master_url.arn
}

output "master_username" {
  value = aws_db_instance.this.username
}

output "parameter_path" {
  description = "Parent path of the database passwords: <path>/master-password and <path>/<user>."
  value       = local.parameter_path
}

output "instance_resource_id" {
  description = "Changes when the database is created again; db-bootstrap runs again then."
  value       = aws_db_instance.this.resource_id
}

output "password_versions" {
  description = "Hash of the version of every password parameter (not of the passwords): it changes when a password changes, so db-bootstrap runs again."
  value = sha256(jsonencode(merge(
    { master = aws_ssm_parameter.master_password.version },
    { for user, parameter in aws_ssm_parameter.component_password : user => parameter.version },
  )))
}
