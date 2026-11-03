# The daily exchange rates (HU-42): one item per day Frankfurter publishes,
# written by the exchange-rates job (securepay-apis) and read by the engine
# (services/decision_engine/currency.py). Same keys as the LocalStack table
# of infra/localstack/init/03_exchange_rates.py.
resource "aws_dynamodb_table" "exchange_rates" {
  name         = "${var.name_prefix}-exchange-rates"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "base"
  range_key    = "rate_date"

  attribute {
    name = "base"
    type = "S"
  }

  attribute {
    name = "rate_date"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  # Encrypted at rest with the AWS owned key (DynamoDB's default).
  deletion_protection_enabled = !var.force_destroy

  tags = { purpose = "Daily exchange rates per 1 USD" }
}
