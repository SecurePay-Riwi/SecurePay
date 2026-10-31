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
