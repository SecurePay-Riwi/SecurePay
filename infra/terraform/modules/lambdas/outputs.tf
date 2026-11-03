output "function_names" {
  description = "Lambda name by component that runs the engine's image (empty until image_tag is set)."
  value       = { for name, function in aws_lambda_function.this : name => function.function_name }
}

output "function_arns" {
  description = "Lambda ARN by component (empty until image_tag is set)."
  value       = { for name, function in aws_lambda_function.this : name => function.arn }
}

output "exchange_rates_function_name" {
  description = "Name of the exchange-rates Lambda (null until apis_image_tag is set)."
  value       = one(aws_lambda_function.exchange_rates[*].function_name)
}
