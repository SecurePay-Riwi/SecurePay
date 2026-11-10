# Entry for people (infrastructure.mdx, "API Gateway + Cognito"): the
# analysts and the risk manager sign in to Cognito and call the rules and
# cases APIs through one HTTP API. API Gateway checks the Cognito token on
# every route but /health and writes the user's e-mail into X-User, which
# both APIs already take as the actor; whatever X-User the caller sent is
# replaced. The engine keeps its own entry (the load balancer).
#
# Created with the Lambdas (enabled): the functions must exist first.

data "aws_region" "current" {}

locals {
  # Paths of each API, as locally: the routes of services/rules_api/main.py
  # and of the route files of services/cases_api.
  routes = {
    "ANY /rules"                   = "rules"
    "ANY /rules/{proxy+}"          = "rules"
    "ANY /cases"                   = "cases"
    "ANY /cases/{proxy+}"          = "cases"
    "ANY /accounts/{proxy+}"       = "cases"
    "ANY /compliance/{proxy+}"     = "cases"
    "ANY /reports/{proxy+}"        = "cases"
    "ANY /reconciliation/{proxy+}" = "cases"
  }
  routes_enabled = var.enabled ? local.routes : {}
  functions      = var.enabled ? { rules = var.rules_function, cases = var.cases_function } : {}
}

# --- Cognito ------------------------------------------------------------------

resource "aws_cognito_user_pool" "this" {
  count = var.enabled ? 1 : 0

  name                     = "${var.name_prefix}-users"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  mfa_configuration        = var.mfa

  dynamic "software_token_mfa_configuration" {
    for_each = var.mfa == "OFF" ? [] : [1]
    content {
      enabled = true
    }
  }

  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = false
  }

  # Users are created by an administrator (var.users, or by hand as in
  # deploy-aws-terraform.mdx), never by signing up.
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

# The two roles of security.mdx (the actors of the brief). The rules API
# answers 403 to a change of the catalog from anyone not in gerente
# (services/rules_api/roles.py); every signed-in user reads.
resource "aws_cognito_user_group" "this" {
  for_each = var.enabled ? toset(["analista", "gerente"]) : toset([])

  name         = each.key
  user_pool_id = aws_cognito_user_pool.this[0].id
}

# One public client (no secret), signing in with user and password from the
# CLI or a script: the ID token carries the e-mail.
resource "aws_cognito_user_pool_client" "this" {
  count = var.enabled ? 1 : 0

  name                          = "${var.name_prefix}-analysts"
  user_pool_id                  = aws_cognito_user_pool.this[0].id
  generate_secret               = false
  explicit_auth_flows           = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors = "ENABLED"
  id_token_validity             = 60
  access_token_validity         = 60
  refresh_token_validity        = 1

  token_validity_units {
    id_token      = "minutes"
    access_token  = "minutes"
    refresh_token = "days"
  }
}

# The demo's users (var.users), so nobody creates them by hand after each
# apply. The e-mail is not sent (SUPPRESS) and the password is permanent:
# `terraform output -json api_user_passwords` gives them.
resource "random_password" "user" {
  for_each = var.enabled ? var.users : {}

  length      = 16
  special     = false
  min_lower   = 1
  min_upper   = 1
  min_numeric = 1
}

resource "aws_cognito_user" "this" {
  for_each = var.enabled ? var.users : {}

  user_pool_id   = aws_cognito_user_pool.this[0].id
  username       = each.key
  password       = random_password.user[each.key].result
  message_action = "SUPPRESS"

  attributes = {
    email          = each.key
    email_verified = true
  }
}

resource "aws_cognito_user_in_group" "this" {
  for_each = var.enabled ? var.users : {}

  user_pool_id = aws_cognito_user_pool.this[0].id
  group_name   = aws_cognito_user_group.this[each.value].name
  username     = aws_cognito_user.this[each.key].username
}

# --- HTTP API -----------------------------------------------------------------

resource "aws_apigatewayv2_api" "this" {
  count = var.enabled ? 1 : 0

  name          = "${var.name_prefix}-api"
  protocol_type = "HTTP"

  # The Rules API and Cases API pages of the site (/rules-api, /cases-api)
  # call it from the browser. API Gateway answers the preflight itself and
  # adds these headers; the Lambdas send none.
  cors_configuration {
    allow_origins = var.cors_origins
    allow_methods = ["GET", "POST", "PUT", "OPTIONS"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 3600
  }
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  count = var.enabled ? 1 : 0

  name             = "cognito"
  api_id           = aws_apigatewayv2_api.this[0].id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    issuer   = "https://cognito-idp.${data.aws_region.current.name}.amazonaws.com/${aws_cognito_user_pool.this[0].id}"
    audience = [aws_cognito_user_pool_client.this[0].id]
  }
}

# The signed-in user's e-mail replaces X-User: the actor of every case event
# and the author of every catalog version.
resource "aws_apigatewayv2_integration" "this" {
  for_each = local.functions

  api_id                 = aws_apigatewayv2_api.this[0].id
  integration_type       = "AWS_PROXY"
  integration_uri        = each.value.arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000

  request_parameters = {
    "overwrite:header.x-user" = "$context.authorizer.claims.email"
  }
}

# /health has no token, so it has its own integration without the mapping.
resource "aws_apigatewayv2_integration" "health" {
  count = var.enabled ? 1 : 0

  api_id                 = aws_apigatewayv2_api.this[0].id
  integration_type       = "AWS_PROXY"
  integration_uri        = var.cases_function.arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "this" {
  for_each = local.routes_enabled

  api_id             = aws_apigatewayv2_api.this[0].id
  route_key          = each.key
  target             = "integrations/${aws_apigatewayv2_integration.this[each.value].id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito[0].id
}

# A preflight carries no token: without this route the JWT authorizer of
# the ANY routes would refuse it before CORS answers.
resource "aws_apigatewayv2_route" "preflight" {
  count = var.enabled ? 1 : 0

  api_id    = aws_apigatewayv2_api.this[0].id
  route_key = "OPTIONS /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.health[0].id}"
}

resource "aws_apigatewayv2_route" "health" {
  count = var.enabled ? 1 : 0

  api_id    = aws_apigatewayv2_api.this[0].id
  route_key = "GET /health"
  target    = "integrations/${aws_apigatewayv2_integration.health[0].id}"
}

resource "aws_cloudwatch_log_group" "access" {
  count = var.enabled ? 1 : 0

  name              = "/aws/apigateway/${var.name_prefix}-api"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_stage" "default" {
  count = var.enabled ? 1 : 0

  api_id      = aws_apigatewayv2_api.this[0].id
  name        = "$default"
  auto_deploy = true

  # A limit per route (infrastructure.mdx): a script loop cannot flood the
  # Lambdas or the database.
  default_route_settings {
    throttling_rate_limit  = var.throttle_rate
    throttling_burst_limit = var.throttle_burst
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access[0].arn
    format = jsonencode({
      requestId = "$context.requestId"
      time      = "$context.requestTime"
      route     = "$context.routeKey"
      status    = "$context.status"
      user      = "$context.authorizer.claims.email"
      latencyMs = "$context.responseLatency"
      error     = "$context.integrationErrorMessage"
    })
  }
}

resource "aws_lambda_permission" "api" {
  for_each = local.functions

  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = each.value.name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this[0].execution_arn}/*/*"
}
