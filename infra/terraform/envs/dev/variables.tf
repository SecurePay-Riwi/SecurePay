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

variable "database_backup_retention_days" {
  description = "Days of automated RDS backups. The design says 7; an AWS account on the free plan accepts at most 1."
  type        = number
  default     = 1
}

variable "database_multi_az" {
  description = "RDS standby in the second zone, as in the design. Creating and deleting it takes 10 to 15 minutes each."
  type        = bool
  default     = true
}

variable "engine_image_tag" {
  description = "Engine image tag in ECR (the short git commit). Leave it unset on the first apply; the engine service starts once it is set."
  type        = string
  default     = null
}

variable "admin_image_tag" {
  description = "securepay-seed image tag in ECR. Leave it unset until the image is pushed."
  type        = string
  default     = null
}

variable "engine_min_tasks" {
  description = "Engine tasks at least, one per zone. The design says 4 in prod."
  type        = number
  default     = 2
}

variable "engine_max_tasks" {
  description = "Engine tasks at most. The design says 24 in prod."
  type        = number
  default     = 4
}

variable "domain_name" {
  description = "Domain for the load balancer certificate. Unset: a self-signed certificate (curl -k)."
  type        = string
  default     = null
}

variable "engine_reads_database" {
  description = "Temporary: the engine still reads PostgreSQL, so dev opens sg-engine -> sg-rds 5432 and hands it DATABASE_URL. Set false once the cache holds that data."
  type        = bool
  default     = true
}
