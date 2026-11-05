variable "name_prefix" {
  description = "Prefix for every resource name, for example securepay-dev."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, prod); part of the parameter paths."
  type        = string
}

variable "github_repository" {
  description = "Repository whose main branch may assume the deploy role."
  type        = string
  default     = "SecurePay-Riwi/SecurePay"
}

variable "github_immutable_subject" {
  description = "Immutable subject prefix of the repository (owner@id/repo@id), shown by `gh api repos/<owner>/<repo>/actions/oidc/customization/sub` as sub_claim_prefix."
  type        = string
  default     = "repo:SecurePay-Riwi@333775069/SecurePay@1387412508"
}

variable "source_deployers" {
  description = "Data-source repositories that deploy their own image: one role each (<prefix>-deploy-<key>) that may push only to the ECR repository <prefix>-<key> and update only its Lambdas. immutable_subject is shown by `gh api repos/<owner>/<repo>/actions/oidc/customization/sub` as sub_claim_prefix."
  type = map(object({
    repository        = string
    immutable_subject = string
    lambdas           = list(string)
  }))
  default = {
    apis = {
      repository        = "SecurePay-Riwi/securepay-apis"
      immutable_subject = "repo:SecurePay-Riwi@333775069/securepay-apis@1426475753"
      lambdas           = ["exchange-rates"]
    }
  }
}

variable "create_github_oidc_provider" {
  description = "Create the GitHub OIDC provider. Set false if the account already has one (there can only be one per account)."
  type        = bool
  default     = true
}


variable "database_users" {
  description = "Database users that db-bootstrap creates; it reads each one's password. Must match USERS in services/db_bootstrap/grants.py (a test checks it)."
  type        = list(string)
  default     = ["alerts", "analytics_export", "cases_api", "cases_consumer", "history_consumer", "list_loader", "reconciliation", "rules_api"]
}
