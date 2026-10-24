provider "aws" {
  region = var.region

  # Project, environment and owner tags on every resource, as the
  # assignment requires (CT-03; infrastructure.mdx, "Tagging").
  default_tags {
    tags = {
      project     = "securepay"
      environment = var.environment
      owner       = var.owner
      managed_by  = "terraform"
    }
  }
}

locals {
  name_prefix = "securepay-${var.environment}"
}

data "aws_availability_zones" "available" {
  state = "available"
}

module "network" {
  source = "../../modules/network"

  name_prefix        = local.name_prefix
  availability_zones = slice(data.aws_availability_zones.available.names, 0, 2)
}

module "security_groups" {
  source = "../../modules/security_groups"

  name_prefix = local.name_prefix
  vpc_id      = module.network.vpc_id
  engine_port = var.engine_port
}

# Budget alert (alarm 10 in infrastructure.mdx). AWS refreshes costs a few
# times a day, so the email can arrive hours after the spend: destroying the
# environment after each test is the real protection.
resource "aws_budgets_budget" "monthly" {
  name         = "${local.name_prefix}-budget"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Count usage paid with credits too: with credits subtracted, the spend
  # they cover shows as USD 0 and the alert would never fire.
  cost_types {
    include_credit = false
    include_refund = false
  }

  dynamic "notification" {
    for_each = var.budget_alert_percentages

    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = var.budget_emails
    }
  }
}

module "iam" {
  source = "../../modules/iam"

  name_prefix                 = local.name_prefix
  environment                 = var.environment
  create_github_oidc_provider = var.create_github_oidc_provider
}

