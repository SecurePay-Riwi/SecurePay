# The daily exchange rates (HU-42): Frankfurter -> DynamoDB, read by the
# engine. It runs the securepay-apis image with its handler; that
# repository's deploy workflow pushes new images and updates the code.
# Outside the VPC: it only calls Frankfurter and DynamoDB, so it needs no
# NAT. Separate from aws_lambda_function.this so it depends only on ECR,
# IAM and the table, and can be applied alone with -target.

locals {
  deploy_exchange_rates = var.apis_image_tag != null
}

resource "aws_cloudwatch_log_group" "exchange_rates" {
  count = local.deploy_exchange_rates ? 1 : 0

  name              = "/aws/lambda/${var.name_prefix}-exchange-rates"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "exchange_rates" {
  count = local.deploy_exchange_rates ? 1 : 0

  function_name = "${var.name_prefix}-exchange-rates"
  role          = var.role_arns["exchange-rates"]
  package_type  = "Image"
  image_uri     = "${var.apis_repository_url}:${var.apis_image_tag}"
  architectures = ["x86_64"]
  memory_size   = 256
  timeout       = 60

  image_config {
    entry_point       = ["python", "-m", "awslambdaric"]
    command           = ["securepay_apis.exchange_rates.handler.handler"]
    working_directory = "/app"
  }

  environment {
    variables = { RATES_TABLE = var.exchange_rates_table }
  }

  logging_config {
    log_format            = "JSON"
    log_group             = aws_cloudwatch_log_group.exchange_rates[0].name
    application_log_level = var.log_level
    system_log_level      = "WARN"
  }
}

# Once a day. If Frankfurter fails, the handler raises and Lambda retries
# the asynchronous call twice; writing the same day again does no harm.
# Meanwhile the engine keeps the last day it loaded.
resource "aws_scheduler_schedule" "exchange_rates" {
  count = local.deploy_exchange_rates ? 1 : 0

  name                = "${var.name_prefix}-exchange-rates"
  schedule_expression = var.exchange_rates_schedule

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.exchange_rates[0].arn
    role_arn = var.role_arns["scheduler"]

    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}
