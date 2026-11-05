output "url" {
  description = "Base URL of the rules and cases APIs (null until the Lambdas exist)."
  value       = one(aws_apigatewayv2_api.this[*].api_endpoint)
}

output "user_pool_id" {
  description = "Cognito user pool of the analysts (null until the Lambdas exist)."
  value       = one(aws_cognito_user_pool.this[*].id)
}

output "client_id" {
  description = "Cognito app client to sign in with (null until the Lambdas exist)."
  value       = one(aws_cognito_user_pool_client.this[*].id)
}
