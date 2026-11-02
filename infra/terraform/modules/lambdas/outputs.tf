output "function_names" {
  description = "Lambda name by component (empty until image_tag is set)."
  value       = { for name, function in aws_lambda_function.this : name => function.function_name }
}
