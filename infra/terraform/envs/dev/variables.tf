variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-2"
}

variable "environment" {
  description = "Environment name, part of every resource name (securepay-<environment>-...)."
  type        = string
  default     = "dev"
}

variable "owner" {
  description = "Person responsible for this environment (owner tag)."
  type        = string
}

variable "engine_port" {
  description = "Port of the decision engine behind the load balancer. security.mdx says 8080; the current image listens on 8000."
  type        = number
  default     = 8000
}

variable "budget_limit_usd" {
  description = "Monthly budget in USD. Low on purpose: dev only lives during a test."
  type        = number
  default     = 5
}

variable "budget_alert_percentages" {
  description = "Percentages of the budget that send an email. Budget alerts are free; AWS allows up to 10 per budget."
  type        = list(number)
  default     = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
}

variable "budget_emails" {
  description = "Addresses that receive the budget alerts."
  type        = list(string)

  validation {
    condition     = length(var.budget_emails) > 0
    error_message = "Give at least one address for the budget alerts."
  }
}

variable "create_github_oidc_provider" {
  description = "Create the GitHub OIDC provider for the deploy role. Set false if the account already has one."
  type        = bool
  default     = true
}
